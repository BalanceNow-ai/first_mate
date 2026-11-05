import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/features/helm_dash/providers/delivery_provider.dart';

import '../../helpers/fakes.dart';
import '../orders/commerce_harness.dart';

void main() {
  final id = fixtureMap('helm_dash_delivery_awaiting_position')['id'] as String;

  CommerceHarness app(WidgetTester tester, FakeBackend backend, {Duration poll = const Duration(seconds: 10)}) =>
      CommerceHarness(tester, backend: backend, overrides: [trackingPollIntervalProvider.overrideWithValue(poll)]);

  testWidgets('accepted without a report: "Awaiting first position report", no boat on the map', (tester) async {
    final backend = fixtureBackend();
    backend.json('GET /helm-dash/deliveries/$id', 200, fixture('helm_dash_delivery_awaiting_position'));
    final a = app(tester, backend);
    await a.start();
    a.go('/dash/$id');
    await a.pump();

    expect(find.text('Awaiting first position report'), findsOneWidget);
    expect(find.text('Skipper accepted your delivery'), findsWidgets);
    expect(find.textContaining('Skipper: Skipper Fixture'), findsOneWidget);
    expect(find.byIcon(Icons.directions_boat), findsNothing, reason: 'no invented position');
    expect(find.text('Updates automatically every 10 seconds.'), findsOneWidget);
    await a.stop();
  });

  testWidgets('a simulated report is labelled and shown once, exactly where reported', (tester) async {
    final backend = fixtureBackend();
    backend.json('GET /helm-dash/deliveries/$id', 200, fixture('helm_dash_delivery_simulated_location'));
    final a = app(tester, backend);
    await a.start();
    a.go('/dash/$id');
    await a.pump();

    final loc = DeliveryTracking.fromJson(fixtureMap('helm_dash_delivery_simulated_location')).latestLocation!;
    expect(find.text('Simulated (local test)'), findsOneWidget);
    expect(find.text(loc.sourceLabel), findsOneWidget);
    expect(find.textContaining('Last reported'), findsOneWidget);
    expect(find.text('Position ${loc.lat.toStringAsFixed(5)}, ${loc.lng.toStringAsFixed(5)}'), findsOneWidget);
    expect(find.byIcon(Icons.directions_boat), findsOneWidget, reason: 'only the latest reported position');
    await a.stop();
  });

  testWidgets('polls while active and stops once delivered', (tester) async {
    final backend = fixtureBackend();
    var n = 0;
    backend.on('GET /helm-dash/deliveries/$id', (_) {
      n++;
      return FakeResponse(200, fixture(n == 1 ? 'helm_dash_delivery_device_location' : 'helm_dash_delivery_delivered'));
    });
    final a = app(tester, backend, poll: const Duration(milliseconds: 100));
    await a.start();
    a.go('/dash/$id');
    await a.pump();
    expect(find.text("Reported by the skipper's device"), findsOneWidget);
    await a.pump(40);
    expect(find.text('Delivered'), findsWidgets);
    final calls = backend.calls('GET /helm-dash/deliveries/$id').length;
    expect(calls, 2);
    await a.pump(20);
    expect(backend.calls('GET /helm-dash/deliveries/$id').length, calls, reason: 'no polling after delivery');
    await a.stop();
  });

  test('age text', () {
    expect(describeAge(const Duration(seconds: 12)), '12 s ago');
    expect(describeAge(const Duration(minutes: 4, seconds: 3)), '4 min ago');
    expect(describeAge(const Duration(hours: 2, minutes: 5)), '2 h 5 min ago');
  });
}
