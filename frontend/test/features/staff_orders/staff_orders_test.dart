import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/features/dispatch/data/dispatch_api.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_orders_screens.dart';

import '../../helpers/fakes.dart';
import '../orders/commerce_harness.dart';

FakeAuthGateway gatewayFor(String meFixture) {
  final me = fixtureMap(meFixture);
  return FakeAuthGateway(token: 'staff-token', userId: me['id'] as String, email: me['email'] as String);
}

FakeBackend backendFor(String meFixture) {
  final b = fixtureBackend();
  b.json('GET /auth/me', 200, fixture(meFixture));
  b.json('POST /auth/provision', 200, fixture(meFixture));
  return b;
}

void main() {
  group('refund idempotency (POST /orders/{id}/refund requires Idempotency-Key)', () {
    test('keys match the server pattern; separate refunds get different keys', () {
      final pattern = RegExp(r'^[A-Za-z0-9_\-:.]{8,100}$');
      final keys = {for (var i = 0; i < 100; i++) newRefundIdempotencyKey()};
      expect(keys, hasLength(100), reason: 'two refunds of the same amount must not share a key');
      expect(keys.every(pattern.hasMatch), isTrue);
      expect(newRefundIdempotencyKey(Random(1)), isNot(newRefundIdempotencyKey(Random(2))));
    });

    test('StaffApi.refund sends the key header, and a retry sends the same key', () async {
      final backend = backendFor('auth_me_admin');
      backend.json('POST /orders/o-1/refund', 202, fixture('order_refund'));
      final c = makeContainer(gateway: gatewayFor('auth_me_admin'), backend: backend);
      addTearDown(c.dispose);
      final api = c.read(staffApiProvider);
      final key = newRefundIdempotencyKey();
      await api.refund('o-1', amountCents: 500, reason: 'Damaged', idempotencyKey: key);
      await api.refund('o-1', amountCents: 500, reason: 'Damaged', idempotencyKey: key);
      final sent = backend.calls('POST /orders/o-1/refund');
      expect(sent, hasLength(2));
      expect(sent.map((r) => r.headers['Idempotency-Key']).toSet(), {key});
      expect(sent.first.body, {'amount_cents': 500, 'reason': 'Damaged'});
    });

    test('a duplicate_request answer is explained as "nothing refunded again"', () {
      final first = RefundResult.fromJson(fixtureMap('order_refund'));
      expect(refundResultText(first), contains(r'Refund succeeded: $5.00'));
      final duplicate = RefundResult.fromJson({...fixtureMap('order_refund'), 'status': 'duplicate_request'});
      expect(refundResultText(duplicate), contains('nothing was refunded again'));
    });
  });

  test('dollars are parsed to integer cents without floating point', () {
    expect(parseDollarsToCents('12.5'), 1250);
    expect(parseDollarsToCents('0.07'), 7);
    expect(parseDollarsToCents('19'), 1900);
    expect(parseDollarsToCents('1.234'), isNull);
    expect(parseDollarsToCents('abc'), isNull);
  });

  test('fulfilment targets follow the server state machine', () {
    final paidCourier = Order.fromJson(fixtureMap('order_paid'));
    expect(fulfilmentTargets(paidCourier), ['ready_for_dispatch']);
    final ready = Order.fromJson(fixtureMap('staff_order_fulfilment'));
    expect(fulfilmentTargets(ready), ['dispatched']);
    final hd = Order.fromJson(fixtureMap('order_helm_dash_paid'));
    expect(fulfilmentTargets(hd), ['ready_for_dispatch', 'dispatched']);
    expect(fulfilmentTargets(Order.fromJson(fixtureMap('order_cancelled'))), isEmpty);
  });

  testWidgets('customers are refused the staff tools (role from /auth/me)', (tester) async {
    final app = CommerceHarness(tester);
    await app.start();
    app.go('/staff/orders');
    await app.pump();
    expect(find.textContaining('Staff orders is only available to dispatcher accounts'), findsOneWidget);
    expect(app.backend.calls('GET /orders/admin/all'), isEmpty);
    await app.stop();
  });

  testWidgets('dispatcher sees staff orders and the test courier label; no refund action', (tester) async {
    final backend = backendFor('auth_me_dispatcher');
    final order = fixtureMap('staff_order_detail');
    backend.json('GET /orders/admin/all', 200, fixture('staff_orders_list'));
    backend.json('GET /orders/admin/${order['id']}', 200, fixture('staff_order_fulfilment'));
    backend.json('POST /orders/${order['id']}/shipment', 201, fixture('staff_order_shipment'));
    final app = CommerceHarness(tester, gateway: gatewayFor('auth_me_dispatcher'), backend: backend);
    await app.start();
    app.go('/staff/orders');
    await app.pump();
    expect(find.text('Order ${order['order_number']}'), findsOneWidget);
    expect(find.textContaining('Customer '), findsWidgets);

    await app.tap(find.text('Order ${order['order_number']}'));
    expect(find.text('Mark dispatched'), findsOneWidget);
    expect(find.text('Refund…'), findsNothing, reason: 'refunds are admin-only');
    await app.tap(find.text('Create courier label (test booking in development)'));
    expect(find.text('TEST courier label created'), findsOneWidget);
    expect(find.textContaining('no real courier was booked'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await app.pump();
    await app.stop();
  });

  testWidgets('admin refund: amount + reason, confirmation, Idempotency-Key header', (tester) async {
    final backend = backendFor('auth_me_admin');
    final order = fixtureMap('order_paid');
    backend.json('GET /orders/admin/${order['id']}', 200, fixture('staff_order_detail'));
    backend.json('POST /orders/${order['id']}/refund', 202, fixture('order_refund'));
    final app = CommerceHarness(tester, gateway: gatewayFor('auth_me_admin'), backend: backend);
    await app.start();
    app.go('/staff/orders/${order['id']}');
    await app.pump();

    await app.tap(find.text('Refund…'));
    await app.enter('Amount (NZD)', '5');
    await app.enter('Reason *', 'Damaged in transit');
    await app.tap(find.text('Continue'));
    expect(find.text(r'Refund $5.00?'), findsOneWidget);
    expect(backend.calls('POST /orders/${order['id']}/refund'), isEmpty, reason: 'nothing before confirmation');
    await app.tap(find.widgetWithText(FilledButton, r'Refund $5.00'));
    final sent = backend.calls('POST /orders/${order['id']}/refund').single;
    expect(sent.body, {'amount_cents': 500, 'reason': 'Damaged in transit'});
    expect(sent.headers['Idempotency-Key'], matches(RegExp(r'^refund-[A-Za-z0-9_\-:.]+$')));
    expect(find.textContaining('TEST MODE — no real money moved'), findsOneWidget);
    await app.stop();
  });
}
