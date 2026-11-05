import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';
import 'package:helm_marine/features/checkout/payment/payment_readiness.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';

import '../../helpers/fakes.dart';
import '../orders/commerce_harness.dart';
import '../staff_orders/staff_orders_test.dart' show backendFor, gatewayFor;
import 'web_card_payment_test.dart' show FakeStripeBridge, stripeConfig;

/// The server's answer for a payment it took but could not apply: succeeded at
/// the provider, never `paid_at`, status `payment_review`.
Map<String, dynamic> underReview(Map<String, dynamic> base) => {
      ...base,
      'status': 'payment_review',
      'payment_status': 'succeeded',
      'paid_at': null,
      'review_reason': 'amount 100 does not match order total 12380',
      'can_cancel': false,
      'can_retry_payment': false,
    };

final quoteTime = DateTime.parse(fixtureMap('quote_courier')['created_at'] as String).add(const Duration(minutes: 1));

void main() {
  group('H1: payment_review is not paid', () {
    test('isPaid comes from the order status / paid_at, not payment_status alone', () {
      final review = Order.fromJson(underReview(fixtureMap('order_paid')));
      expect(review.paymentStatus, 'succeeded');
      expect(review.isPaid, isFalse);
      expect(review.isUnderPaymentReview, isTrue);
      expect(review.isRefundable, isTrue, reason: 'staff can still refund the captured money');
      expect(phaseOf(review), PaymentPhase.underReview);

      expect(Order.fromJson(fixtureMap('order_paid')).isPaid, isTrue);
      for (final s in ['ready_for_dispatch', 'dispatched', 'delivered', 'collected']) {
        expect(Order.fromJson({...fixtureMap('order_paid'), 'status': s}).isPaid, isTrue, reason: s);
      }
      final refundedAfterPaid = {...fixtureMap('order_paid'), 'status': 'refunded', 'payment_status': 'refunded'};
      expect(Order.fromJson(refundedAfterPaid).isPaid, isTrue);
      expect(Order.fromJson({...refundedAfterPaid, 'paid_at': null}).isPaid, isFalse,
          reason: 'a refunded review order was never paid');
      expect(Order.fromJson({...fixtureMap('order_checkout_created'), 'payment_status': 'succeeded'}).isPaid, isFalse);
    });

    testWidgets('payment panel shows "under review", never "Payment confirmed"', (tester) async {
      final backend = fixtureBackend();
      final order = fixtureMap('order_checkout_created');
      final id = order['id'] as String;
      backend.json('GET /orders/$id', 200, underReview(order));
      final app = CommerceHarness(tester, backend: backend);
      await app.start();
      app.go('/orders/$id/pay');
      await app.pump();
      expect(find.text('Payment under review'), findsWidgets); // notice title and status chip
      expect(find.textContaining("Payment received but the order needs staff review; you'll be contacted or refunded."),
          findsOneWidget);
      expect(find.text('Payment confirmed'), findsNothing);
      expect(backend.calls('POST /payments/orders/$id/intent'), isEmpty);
      await app.stop();
    });

    testWidgets('staff: no courier label for a payment_review order; refund stays available', (tester) async {
      final backend = backendFor('auth_me_admin');
      final order = underReview(fixtureMap('staff_order_detail'));
      backend.json('GET /orders/admin/${order['id']}', 200, order);
      final app = CommerceHarness(tester, gateway: gatewayFor('auth_me_admin'), backend: backend);
      await app.start();
      app.go('/staff/orders/${order['id']}');
      await app.pump();
      final label = find.widgetWithText(OutlinedButton, 'Create courier label (test booking in development)');
      await tester.ensureVisible(label);
      expect(tester.widget<OutlinedButton>(label).onPressed, isNull);
      expect(tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Refund…')).onPressed, isNotNull);
      await app.stop();
    });

    testWidgets('Low: an unpaid local order is not described as paid', (tester) async {
      final backend = fixtureBackend();
      final order = fixtureMap('order_checkout_created');
      backend.json('GET /orders/${order['id']}', 200, order);
      final app = CommerceHarness(tester, backend: backend);
      await app.start();
      app.go('/orders/${order['id']}');
      await app.pump();
      expect(find.text('Awaiting payment'), findsWidgets);
      expect(find.textContaining('Paid through the local TEST MODE provider'), findsNothing);
      await app.stop();

      final paid = fixtureMap('order_paid');
      final backend2 = fixtureBackend()..json('GET /orders/${paid['id']}', 200, paid);
      final app2 = CommerceHarness(tester, backend: backend2);
      await app2.start();
      app2.go('/orders/${paid['id']}');
      await app2.pump();
      expect(find.textContaining('Paid through the local TEST MODE provider'), findsOneWidget);
      await app2.stop();
    });
  });

  group('H2: never reserve stock this device cannot pay for', () {
    FakeBackend checkoutBackend(Object config) {
      final b = fixtureBackend();
      b.json('GET /config/public', 200, config);
      b.json('GET /cart/', 200, fixture('cart_with_item'));
      b.json('GET /shipping/options', 200, fixture('shipping_options'));
      b.json('GET /loyalty/entitlements', 200, fixture('loyalty_entitlements_issued'));
      b.json('POST /orders/checkout/preview', 200, fixture('checkout_preview_click_and_collect'));
      b.on('POST /orders/checkout', (_) => FakeResponse(201, fixtureMap('order_click_and_collect_created')));
      return b;
    }

    Future<CommerceHarness> toReview(WidgetTester tester, FakeBackend backend, List<Override> overrides) async {
      final app = CommerceHarness(tester, backend: backend, overrides: [
        checkoutClockProvider.overrideWithValue(() => quoteTime),
        ...overrides,
      ]);
      await app.start();
      app.go('/checkout');
      await app.pump();
      await app.tap(find.text('Click & collect'));
      await app.tap(find.text('Continue to review'));
      return app;
    }

    FilledButton placeButton(WidgetTester tester) =>
        tester.widget<FilledButton>(find.ancestor(of: find.textContaining('Place order'), matching: find.byType(FilledButton)));

    testWidgets('web: Stripe.js fails to load at review → Place order blocked, no order; retry unblocks',
        (tester) async {
      final bridge = FakeStripeBridge()..loadOutcomes.add(const StripeWebFailure('Stripe.js could not be loaded.'));
      final backend = checkoutBackend(stripeConfig());
      final app = await toReview(tester, backend, [stripeWebBridgeFactoryProvider.overrideWithValue(() => bridge)]);

      expect(find.text("You can't pay on this device right now"), findsOneWidget);
      expect(find.textContaining('Card payments are unavailable right now: Stripe.js could not be loaded.'),
          findsOneWidget);
      expect(find.textContaining('No order has been placed and nothing is reserved.'), findsOneWidget);
      expect(placeButton(tester).onPressed, isNull);
      expect(backend.calls('POST /orders/checkout'), isEmpty);

      await app.tap(find.text('Try again'));
      expect(bridge.loadCalls, 2);
      expect(find.text("You can't pay on this device right now"), findsNothing);
      expect(placeButton(tester).onPressed, isNotNull);
      await app.stop();
    });

    testWidgets('stripe with no web bridge and no native sheet → blocked before any order', (tester) async {
      final backend = checkoutBackend(stripeConfig());
      final app = await toReview(tester, backend, [
        stripeWebBridgeFactoryProvider.overrideWithValue(null),
        stripeNativeSheetSupportedProvider.overrideWithValue(false),
      ]);
      expect(find.textContaining('Card payments are not available in this version of the app.'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
      expect(placeButton(tester).onPressed, isNull);
      expect(backend.calls('POST /orders/checkout'), isEmpty);
      await app.stop();
    });

    test('readiness: local is ready; stripe on web is ready once Stripe.js loads', () async {
      final local = makeContainer(gateway: fixtureGateway(), backend: checkoutBackend(fixture('config_public')));
      addTearDown(local.dispose);
      final sub = local.listen(paymentReadinessProvider, (_, _) {});
      addTearDown(sub.close);
      expect((await local.read(paymentReadinessProvider.future)).ready, isTrue);

      final bridge = FakeStripeBridge();
      final web = ProviderContainer(overrides: [
        ...testOverrides(gateway: fixtureGateway(), backend: checkoutBackend(stripeConfig())),
        stripeWebBridgeFactoryProvider.overrideWithValue(() => bridge),
      ]);
      addTearDown(web.dispose);
      final sub2 = web.listen(paymentReadinessProvider, (_, _) {});
      addTearDown(sub2.close);
      expect((await web.read(paymentReadinessProvider.future)).ready, isTrue);
      expect(bridge.loadCalls, 1);
      expect(bridge.disposeCalls, 1);
    });
  });

  group('M1: a stale checkout attempt never hijacks a later checkout', () {
    late FakeBackend backend;
    late Map<String, dynamic> current;
    late String orderId;

    Future<ProviderContainer> signedIn() async {
      final c = ProviderContainer(
        overrides: [
          ...testOverrides(gateway: fixtureGateway(), backend: backend),
          checkoutClockProvider.overrideWithValue(() => quoteTime),
        ],
        retry: (_, _) => null,
      );
      addTearDown(c.dispose);
      c.read(authControllerProvider);
      await until(() => c.read(authControllerProvider).isSignedIn);
      return c;
    }

    setUp(() {
      backend = fixtureBackend();
      current = fixtureMap('order_checkout_created');
      orderId = current['id'] as String;
      backend.on('POST /orders/checkout', (_) => FakeResponse(201, current));
      backend.on('GET /orders/$orderId', (_) => FakeResponse(200, current));
    });

    const req = CheckoutRequest(deliveryType: DeliveryType.clickAndCollect);

    test('held order paid elsewhere → reset on entry; still pending → kept', () async {
      final c = await signedIn();
      final ctl = c.read(checkoutProvider.notifier);
      await ctl.placeOrder(req);
      expect(c.read(checkoutProvider).orderId, orderId);

      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).orderId, orderId, reason: 'still pending_payment: same attempt');

      current = fixtureMap('order_paid');
      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).orderId, isNull);
      expect(c.read(checkoutProvider).attemptKey, isNull);
    });

    test('held order + a new non-empty cart → fresh attempt', () async {
      final c = await signedIn();
      final ctl = c.read(checkoutProvider.notifier);
      await ctl.placeOrder(req);
      backend.json('GET /cart/', 200, fixture('cart_with_item'));
      c.invalidate(cartProvider);
      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).orderId, isNull);
    });

    test('a lost response keeps its key for the same cart, but not for a changed cart', () async {
      backend.json('GET /cart/', 200, fixture('cart_with_item'));
      backend.on('POST /orders/checkout', (_) => throw Exception('connection reset'));
      final c = await signedIn();
      await c.read(cartProvider.future);
      final ctl = c.read(checkoutProvider.notifier);
      expect(await ctl.placeOrder(req), isNull);
      final key = c.read(checkoutProvider).attemptKey!;

      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).attemptKey, key, reason: 'same cart: retries stay idempotent');

      // The lost response did create the order and moved the cart: empty cart keeps the key.
      backend.json('GET /cart/', 200, fixture('cart_empty'));
      c.invalidate(cartProvider);
      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).attemptKey, key);

      // A different cart is a different attempt.
      final changed = fixtureMap('cart_with_item');
      final items = [for (final i in changed['items'] as List) {...(i as Map).cast<String, dynamic>(), 'quantity': 7}];
      backend.json('GET /cart/', 200, {...changed, 'items': items});
      c.invalidate(cartProvider);
      await ctl.reconcileOnEntry();
      expect(c.read(checkoutProvider).attemptKey, isNull);
    });

    testWidgets('/orders/:id/pay reaching a terminal state resets the attempt; /checkout starts fresh',
        (tester) async {
      backend.json('GET /config/public', 200, fixture('config_public'));
      backend.json('POST /payments/orders/$orderId/intent', 200, fixture('payment_intent_local'));
      final pi = fixtureMap('payment_intent_local')['payment_intent_id'];
      backend.on('POST /payments/local/$pi/confirm', (_) {
        current = fixtureMap('order_paid');
        return FakeResponse(200, fixture('payment_local_succeed'));
      });
      backend.json('GET /shipping/options', 200, fixture('shipping_options'));
      final app = CommerceHarness(tester, backend: backend, overrides: [
        paymentPollIntervalProvider.overrideWithValue(Duration.zero),
        paymentPollAttemptsProvider.overrideWithValue(2),
      ]);
      await app.start();
      await tester.runAsync(() => app.container.read(checkoutProvider.notifier).placeOrder(req));
      expect(app.container.read(checkoutProvider).orderId, orderId);

      app.go('/orders/$orderId/pay');
      await app.pump();
      await app.tap(find.text('Simulate success'));
      expect(find.text('Payment confirmed'), findsOneWidget);
      expect(app.container.read(checkoutProvider).orderId, isNull);

      app.go('/checkout');
      await app.pump();
      expect(find.text('Payment confirmed'), findsNothing);
      expect(find.textContaining('Pay for order'), findsNothing);
      await app.stop();
    });
  });
}
