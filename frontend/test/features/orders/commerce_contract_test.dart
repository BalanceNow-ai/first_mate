// Contract tests for checkout, orders, payments, Helm Dash and dispatch: the
// models parse REAL payloads captured from the running stack by
// scripts/capture_api_fixtures_pass2_commerce.py (test/fixtures/api/*.json).
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/config/public_config.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';

import '../../helpers/fakes.dart';

List<Map<String, dynamic>> fixtureList(String name) =>
    [for (final e in fixture(name) as List) (e as Map).cast<String, dynamic>()];

ApiError errorFixture(String name, int status) => ApiError.fromResponse(status, fixtureMap(name));

void main() {
  group('public config', () {
    test('Helm Dash enabled; Afterpay/Laybuy disabled with recorded reasons', () {
      final c = PublicConfig.fromJson(fixtureMap('config_public_helm_dash'));
      expect(c.delivery.helmDash.enabled, isTrue);
      expect(c.payments.provider, 'local');
      expect(c.payments.method('card')!.enabled, isTrue);
      for (final id in ['afterpay', 'laybuy']) {
        expect(c.payments.method(id)!.enabled, isFalse);
        expect(c.payments.method(id)!.reason, contains('not offered'));
      }
    });
  });

  group('delivery options and quotes', () {
    test('GET /shipping/options lists all three types with server prices', () {
      final o = DeliveryOptions.fromJson(fixtureMap('shipping_options'));
      expect(o.options.map((x) => x.deliveryType),
          containsAll([DeliveryType.courier, DeliveryType.helmDash, DeliveryType.clickAndCollect]));
      final cc = o.option(DeliveryType.clickAndCollect)!;
      expect(cc.priceCents, 0);
      expect(cc.requiresQuote, isFalse);
      expect(cc.pickupLocation, isNotEmpty);
      final hd = o.option(DeliveryType.helmDash)!;
      expect(hd.priceCents, isNull, reason: 'Helm Dash is priced by quote');
      expect(hd.operatingAreas.single.id, 'hauraki-gulf');
      expect(hd.operatingAreas.single.radiusMetres, closeTo(25 * 1852, 0.001));
      expect(o.option(DeliveryType.courier)!.developmentRateCard, isTrue);
    });

    test('dangerous goods disable courier and Helm Dash with the reason', () {
      final o = DeliveryOptions.fromJson(fixtureMap('shipping_options_dangerous_goods'));
      expect(o.dangerousGoodsProducts.single.sku, 'SYN-FLARE-KIT');
      for (final t in [DeliveryType.courier, DeliveryType.helmDash]) {
        final opt = o.option(t)!;
        expect(opt.available, isFalse);
        expect(opt.reasonCode, 'dangerous_goods_restricted');
        expect(opt.reason, contains('Dangerous goods'));
      }
      expect(o.option(DeliveryType.clickAndCollect)!.available, isTrue);
    });

    test('courier and Helm Dash quotes', () {
      final c = DeliveryQuote.fromJson(fixtureMap('quote_courier'));
      expect(c.deliveryType, DeliveryType.courier);
      expect(c.postcode, '1010');
      expect(c.priceCents, greaterThan(0));
      expect(c.expiresAt.isAfter(c.createdAt), isTrue);
      expect(c.estimatedDays, isNotNull);
      final h = DeliveryQuote.fromJson(fixtureMap('quote_helm_dash'));
      expect(h.nauticalMiles, isNotNull);
      expect(h.estimatedMinutes, isNotNull);
      expect(h.operatingAreaId, 'hauraki-gulf');
      expect(h.destination['location_name'], 'Motuihe Channel anchorage');
    });

    test('public areas', () {
      final areas = [for (final a in fixtureList('helm_dash_areas')) OperatingAreaSummary.fromJson(a)];
      expect(areas.single.centerLat, -36.75);
    });
  });

  group('checkout preview', () {
    test('courier preview adds the quoted shipping', () {
      final p = CheckoutPreview.fromJson(fixtureMap('checkout_preview_courier'));
      final q = DeliveryQuote.fromJson(fixtureMap('quote_courier'));
      expect(p.quoteId, q.id);
      expect(p.totalCents, p.subtotalCents - p.discountCents + p.shippingCents);
      expect(p.shippingCents, q.priceCents);
    });

    test('click & collect is zero shipping with the pickup location', () {
      final p = CheckoutPreview.fromJson(fixtureMap('checkout_preview_click_and_collect'));
      expect(p.shippingCents, 0);
      expect(p.pickupLocation, isNotEmpty);
      expect(p.quoteId, isNull);
    });

    test('Helm Dash preview and discount preview', () {
      final h = CheckoutPreview.fromJson(fixtureMap('checkout_preview_helm_dash'));
      expect(h.deliveryType, DeliveryType.helmDash);
      expect(h.shippingCents, greaterThan(0));
      final d = CheckoutPreview.fromJson(fixtureMap('checkout_preview_with_discount'));
      expect(d.discountCents, 100);
      expect(d.totalCents, d.subtotalCents - 100);
    });

    test('issued entitlements', () {
      final e = DiscountEntitlement.fromJson(fixtureList('loyalty_entitlements_issued').single);
      expect(e.status, 'issued');
      expect(e.amountCents, 100);
      expect(e.code, startsWith('CREW-'));
    });
  });

  group('orders', () {
    test('checkout 201 then idempotent 200 return the same order', () {
      final a = Order.fromJson(fixtureMap('order_checkout_created'));
      final b = Order.fromJson(fixtureMap('order_checkout_existing'));
      expect(b.id, a.id);
      expect(a.status, 'pending_payment');
      expect(a.paymentStatus, 'unpaid');
      expect(a.canCancel, isTrue);
      expect(a.canRetryPayment, isTrue);
      expect(a.expiresAt, isNotNull);
      expect(a.delivery.shippingAddress!['postcode'], '1010');
      expect(a.items, isNotEmpty);
      expect(a.totalCents, a.subtotalCents - a.discountCents + a.shippingCents);
      expect(phaseOf(a), PaymentPhase.ready);
    });

    test('the cart is emptied by checkout and restored by cancel', () {
      expect(Cart.fromJson(fixtureMap('cart_after_checkout')).isEmpty, isTrue);
      expect(Cart.fromJson(fixtureMap('cart_after_cancel')).isEmpty, isFalse);
    });

    test('payment states map to phases', () {
      expect(phaseOf(Order.fromJson(fixtureMap('order_payment_failed'))), PaymentPhase.failed);
      expect(phaseOf(Order.fromJson(fixtureMap('order_requires_action'))), PaymentPhase.requiresAction);
      final paid = Order.fromJson(fixtureMap('order_paid'));
      expect(phaseOf(paid), PaymentPhase.paid);
      expect(paid.paidAt, isNotNull);
      expect(paid.canCancel, isFalse);
      final cancelled = Order.fromJson(fixtureMap('order_cancelled'));
      expect(phaseOf(cancelled), PaymentPhase.cancelled);
      expect(cancelled.cancelReason, 'customer_cancelled');
    });

    test('Helm Dash order carries the destination and contact', () {
      final o = Order.fromJson(fixtureMap('order_helm_dash_paid'));
      expect(o.isHelmDash, isTrue);
      expect(o.delivery.helmDash!['vessel_name'], 'Sea Biscuit');
      expect(o.delivery.estimatedMinutes, isNotNull);
    });

    test('test courier tracking and partial refund', () {
      final t = Order.fromJson(fixtureMap('order_with_test_tracking'));
      expect(t.tracking.isTest, isTrue);
      expect(t.tracking.trackingNumber, startsWith('TEST-'));
      final r = Order.fromJson(fixtureMap('order_partially_refunded'));
      expect(r.refundedCents, 500);
      expect(r.paymentStatus, 'partially_refunded');
      expect(paymentStatusLabel(r.paymentStatus), 'Partially refunded');
    });

    test('order list page', () {
      final p = OrderPage.fromJson(fixtureMap('orders_list'));
      expect(p.items, hasLength(p.total));
      expect(p.page, 1);
      expect(p.hasNext, isFalse);
      expect(p.items.first.userId, isNull);
    });
  });

  group('payments', () {
    test('local intent is test mode and reused on retry', () {
      final a = PaymentIntentInfo.fromJson(fixtureMap('payment_intent_local'));
      final b = PaymentIntentInfo.fromJson(fixtureMap('payment_intent_retry'));
      expect(a.isLocal, isTrue);
      expect(a.testMode, isTrue);
      expect(a.publishableKey, isNull);
      expect(b.paymentIntentId, a.paymentIntentId);
      expect(a.amountCents, Order.fromJson(fixtureMap('order_checkout_created')).totalCents);
    });

    test('local confirmations report the applied signed event', () {
      final d = LocalConfirmResult.fromJson(fixtureMap('payment_local_decline'));
      expect(d.eventType, 'payment_intent.payment_failed');
      expect(d.paymentStatus, 'failed');
      expect(LocalConfirmResult.fromJson(fixtureMap('payment_local_requires_action')).paymentStatus, 'requires_action');
      expect(LocalConfirmResult.fromJson(fixtureMap('payment_local_authenticate')).orderStatus, 'paid');
      expect(LocalConfirmResult.fromJson(fixtureMap('payment_local_succeed')).eventOutcome, 'applied');
    });
  });

  group('Helm Dash tracking', () {
    test('awaiting dispatch: no position, explanatory message', () {
      final t = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_awaiting_dispatch'));
      expect(t.latestLocation, isNull);
      expect(t.locationMessage, contains('Tracking starts'));
      expect(t.operatorDisplayName, isNull);
      expect(t.isActive, isTrue);
    });

    test('accepted without a report: "Awaiting first position report"', () {
      final t = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_awaiting_position'));
      expect(t.status, 'accepted');
      expect(t.latestLocation, isNull);
      expect(t.locationMessage, 'Awaiting first position report');
      expect(t.operatorDisplayName, isNotNull);
    });

    test('simulated and device positions are labelled', () {
      final s = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_simulated_location')).latestLocation!;
      expect(s.isSimulated, isTrue);
      expect(s.source, 'simulated');
      final d = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_device_location')).latestLocation!;
      expect(d.isSimulated, isFalse);
      expect(d.source, 'operator_device');
      expect(d.accuracyM, 12.0);
    });

    test('delivered timeline', () {
      final t = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_delivered'));
      expect(t.isActive, isFalse);
      expect(t.timeline.last.status, 'delivered');
      expect(fixtureList('helm_dash_deliveries').map(DeliveryTracking.fromJson), isNotEmpty);
    });
  });

  group('dispatch and staff', () {
    test('staff roles from /auth/me', () {
      expect(User.fromJson(fixtureMap('auth_me_dispatcher')).role, 'dispatcher');
      expect(User.fromJson(fixtureMap('auth_me_operator')).role, 'operator');
      expect(User.fromJson(fixtureMap('auth_me_admin')).role, 'admin');
    });

    test('deliveries, detail with events and location, assignment', () {
      final list = fixtureList('dispatch_deliveries').map(DispatchDelivery.fromJson).toList();
      expect(list, isNotEmpty);
      expect(list.first.events, isNull);
      final detail = DispatchDelivery.fromJson(fixtureMap('dispatch_delivery_detail'));
      expect(detail.events, isNotEmpty);
      expect(detail.latestLocation!.source, 'operator_device');
      expect(detail.acceptsPositions, isTrue);
      final awaiting = DispatchDelivery.fromJson(fixtureMap('dispatch_delivery_detail_awaiting'));
      expect(awaiting.latestLocation, isNull);
      final assigned = DispatchDelivery.fromJson(fixtureMap('dispatch_delivery_assigned'));
      expect(assigned.status, 'assigned');
      expect(assigned.operatorId, isNotNull);
    });

    test('operators, areas, operator jobs', () {
      final ops = fixtureList('dispatch_operators').map(OperatorProfile.fromJson).toList();
      expect(ops.single.active, isTrue);
      expect(ops.single.certificationVerified, isFalse);
      expect(OperatorProfile.fromJson(fixtureMap('dispatch_operator_created')).active, isFalse);
      expect(OperatorProfile.fromJson(fixtureMap('operator_availability')).isOnline, isTrue);
      expect(OperatorProfile.fromJson(fixtureMap('operator_me')).displayName, isNotEmpty);
      expect(OperatingArea.fromJson(fixtureList('dispatch_areas').single).enabled, isTrue);
      expect(fixtureList('operator_jobs').map(DispatchDelivery.fromJson).single.status, 'assigned');
      expect(DispatchDelivery.fromJson(fixtureMap('operator_job_accepted')).status, 'accepted');
      expect(DispatchDelivery.fromJson(fixtureMap('operator_job_picked_up')).status, 'picked_up');
      expect(DispatchDelivery.fromJson(fixtureMap('operator_job_delivered')).isTerminal, isTrue);
      expect(DispatchDelivery.fromJson(fixtureMap('operator_job_detail')).events, isNotEmpty);
      expect(fixtureList('operator_jobs_finished').map(DispatchDelivery.fromJson), isNotEmpty);
      final receipt = LocationReceipt.fromJson(fixtureMap('operator_location_created'));
      expect(receipt.source, 'operator_device');
    });

    test('payouts are rate_unconfigured with no amount; reconciliation', () {
      final p = Payout.fromJson(fixtureList('dispatch_payouts').single);
      expect(p.status, 'rate_unconfigured');
      expect(p.amountCents, isNull);
      expect(p.shareBps, isNull);
      final r = Reconciliation.fromJson(fixtureMap('dispatch_reconciliation'));
      expect(r.livePayoutsEnabled, isFalse);
      expect(r.operatorShareBps, isNull);
      expect(r.payoutsByStatus.first.status, 'rate_unconfigured');
    });

    test('staff orders, fulfilment, shipment, refund', () {
      final list = OrderPage.fromJson(fixtureMap('staff_orders_list'));
      expect(list.items.every((o) => o.userId != null), isTrue);
      final detail = Order.fromJson(fixtureMap('staff_order_detail'));
      expect(detail.userId, isNotNull);
      expect(Order.fromJson(fixtureMap('staff_order_fulfilment')).status, 'ready_for_dispatch');
      final s = Shipment.fromJson(fixtureMap('staff_order_shipment'));
      expect(s.isTest, isTrue);
      expect(s.labelReference, startsWith('TEST-LABEL'));
      final r = RefundResult.fromJson(fixtureMap('order_refund'));
      expect(r.testMode, isTrue);
      expect(r.amountCents, 500);
      expect(r.paymentStatus, 'partially_refunded');
    });
  });

  group('error payloads', () {
    final cases = <String, (int, String)>{
      'error_dangerous_goods_restricted': (422, 'dangerous_goods_restricted'),
      'error_validation_postcode': (422, 'validation_error'),
      'error_outside_operating_area': (422, 'outside_operating_area'),
      'error_idempotency_key_required': (400, 'idempotency_key_required'),
      'error_payment_method_unavailable': (422, 'payment_method_unavailable'),
      'error_quote_destination_mismatch': (422, 'quote_destination_mismatch'),
      'error_quote_required': (422, 'quote_required'),
      'error_quote_cart_changed': (409, 'quote_cart_changed'),
      'error_checkout_insufficient_stock': (409, 'insufficient_stock'),
      'error_order_already_paid': (409, 'order_already_paid'),
      'error_order_not_cancellable': (409, 'order_not_cancellable'),
      'error_helm_dash_contact_required': (422, 'helm_dash_contact_required'),
      'error_delivery_not_found': (404, 'not_found'),
      'error_forbidden': (403, 'forbidden'),
      'error_operator_not_active': (403, 'operator_not_active'),
      'error_already_assigned': (409, 'already_assigned'),
      'error_location_stale': (422, 'location_stale'),
      'error_invalid_transition': (409, 'invalid_transition'),
      'error_rate_unconfigured': (409, 'rate_unconfigured'),
      'error_invalid_filter': (422, 'invalid_filter'),
      'error_not_a_courier_order': (409, 'not_a_courier_order'),
      'error_refund_forbidden': (403, 'forbidden'),
    };
    for (final entry in cases.entries) {
      test('${entry.key} → ${entry.value.$2}', () {
        final e = errorFixture(entry.key, entry.value.$1);
        expect(e.code, entry.value.$2);
        expect(e.detail, isNotEmpty);
      });
    }

    test('extras: restricted products and product ids', () {
      final dg = errorFixture('error_dangerous_goods_restricted', 422);
      expect((dg.extra['products'] as List).single['sku'], 'SYN-FLARE-KIT');
      expect(dg.extra['allowed_delivery_types'], ['click_and_collect']);
      final stock = errorFixture('error_checkout_insufficient_stock', 409);
      expect(stock.extra['product_ids'], isNotEmpty);
      final v = errorFixture('error_validation_postcode', 422);
      expect(v.errors.first.field, 'postcode');
    });
  });
}
