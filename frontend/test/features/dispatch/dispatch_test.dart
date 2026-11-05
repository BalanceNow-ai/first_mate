import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/dispatch/data/geolocation.dart';
import 'package:helm_marine/features/dispatch/screens/operator_screens.dart';

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
  final delivery = fixtureMap('dispatch_delivery_detail_awaiting');
  final id = delivery['id'] as String;

  testWidgets('dispatcher assigns an active operator from the area', (tester) async {
    final backend = backendFor('auth_me_dispatcher');
    backend.json('GET /dispatch/areas', 200, fixture('dispatch_areas'));
    backend.json('GET /dispatch/deliveries', 200, fixture('dispatch_deliveries'));
    backend.json('GET /dispatch/deliveries/$id', 200, delivery);
    backend.json('GET /dispatch/operators', 200, fixture('dispatch_operators'));
    backend.json('POST /dispatch/deliveries/$id/assign', 200, fixture('dispatch_delivery_assigned'));
    final app = CommerceHarness(tester, gateway: gatewayFor('auth_me_dispatcher'), backend: backend);
    await app.start();
    app.go('/staff/dispatch');
    await app.pump();
    expect(find.text('Order ${delivery['order_number']}'), findsOneWidget);
    expect(backend.calls('GET /dispatch/deliveries').single.query, {'active_only': 'true'});

    await app.tap(find.text('Order ${delivery['order_number']}'));
    expect(find.text('Assign a skipper'), findsOneWidget);
    expect(backend.calls('GET /dispatch/operators').single.query, {'area_id': 'hauraki-gulf', 'active': 'true'});
    final op = (fixture('dispatch_operators') as List).single as Map;
    await app.tap(find.text('Operator'));
    await app.tap(find.textContaining(op['display_name'] as String).last);
    await app.tap(find.text('Assign'));
    expect(backend.calls('POST /dispatch/deliveries/$id/assign').single.body, {'operator_id': op['user_id']});
    await app.stop();
  });

  testWidgets('operator shares a position only after the explicit action; server errors are shown', (tester) async {
    final job = fixtureMap('operator_job_detail');
    final jobId = job['id'] as String;
    final backend = backendFor('auth_me_operator');
    backend.json('GET /dispatch/jobs/$jobId', 200, {...job, 'status': 'picked_up'});
    var reply = const FakeResponse(422, {'detail': 'recorded_at is too old to be a live position', 'code': 'location_stale'});
    backend.on('POST /dispatch/jobs/$jobId/location', (_) => reply);
    var reads = 0;
    final recorded = DateTime.utc(2026, 11, 5, 7, 30, 1);
    final app = CommerceHarness(
      tester,
      gateway: gatewayFor('auth_me_operator'),
      backend: backend,
      overrides: [
        geolocationAvailableProvider.overrideWithValue(true),
        devicePositionReaderProvider.overrideWithValue(() async {
          reads++;
          return DeviceReading(lat: -36.81, lng: 174.82, recordedAt: recorded, accuracyM: 8);
        }),
      ],
    );
    await app.start();
    app.go('/staff/operator/jobs/$jobId');
    await app.pump();
    expect(find.text('Mark en route'), findsOneWidget);
    expect(reads, 0, reason: 'nothing is read before the user asks');

    await app.tap(find.text('Share my current position'));
    expect(find.text('Share your current position?'), findsOneWidget);
    expect(reads, 0);
    await app.tap(find.widgetWithText(FilledButton, 'Share position'));
    expect(reads, 1);
    final body = backend.calls('POST /dispatch/jobs/$jobId/location').single.body as Map;
    expect(body, {'lat': -36.81, 'lng': 174.82, 'recorded_at': '2026-11-05T07:30:01.000Z', 'accuracy_m': 8.0});
    expect(find.textContaining('too old to share as a live position'), findsOneWidget);

    reply = FakeResponse(201, fixture('operator_location_created'));
    await app.tap(find.text('Share my current position'));
    await app.tap(find.widgetWithText(FilledButton, 'Share position'));
    expect(find.textContaining('Position shared'), findsOneWidget);
    await app.stop();
  });

  testWidgets('admin sees rate_unconfigured payouts explained and no approve action', (tester) async {
    final backend = backendFor('auth_me_admin');
    backend.json('GET /dispatch/areas', 200, fixture('dispatch_areas'));
    backend.json('GET /dispatch/payouts', 200, fixture('dispatch_payouts'));
    backend.json('GET /dispatch/operators', 200, fixture('dispatch_operators'));
    backend.json('GET /dispatch/reconciliation', 200, fixture('dispatch_reconciliation'));
    final app = CommerceHarness(tester, gateway: gatewayFor('auth_me_admin'), backend: backend);
    await app.start();
    app.go('/staff/admin');
    await app.pump();
    expect(find.text('Hauraki Gulf (local demo area)'), findsOneWidget);
    await app.tap(find.text('Payouts'));
    expect(find.textContaining('No operator share is configured (decision D10)'), findsOneWidget);
    expect(find.text('Approve'), findsNothing);
    await app.tap(find.text('Reconciliation'));
    expect(find.text('not configured'), findsOneWidget);
    expect(find.text('disabled'), findsOneWidget);
    await app.stop();
  });
}
