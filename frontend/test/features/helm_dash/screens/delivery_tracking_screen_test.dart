import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/helm_dash/providers/delivery_provider.dart';
import 'package:helm_marine/features/helm_dash/screens/delivery_tracking_screen.dart';

void main() {
  group('DeliveryTrackingScreen', () {
    Widget buildTestWidget({
      required AsyncValue<Map<String, dynamic>> deliveryState,
      AsyncValue<DeliveryLocation>? locationState,
    }) {
      return ProviderScope(
        overrides: [
          deliveryDetailProvider('test-delivery').overrideWith((ref) async {
            if (deliveryState is AsyncError) throw deliveryState.error!;
            return deliveryState.value!;
          }),
          if (locationState != null)
            deliveryLiveLocationProvider('test-delivery')
                .overrideWith((ref) async {
              if (locationState is AsyncError) throw locationState.error!;
              return locationState.value!;
            }),
        ],
        child: const MaterialApp(
          home: DeliveryTrackingScreen(deliveryId: 'test-delivery'),
        ),
      );
    }

    testWidgets('shows delivery tracking title', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        deliveryState: const AsyncData({
          'status': 'en_route',
          'delivery_coordinates': {'lat': -36.87, 'lng': 174.78},
          'nautical_miles': 5.2,
          'delivery_fee': 66.60,
          'estimated_delivery_minutes': 27,
          'operator_name': 'Captain Jack',
          'delivery_location_name': 'Rangitoto Channel',
        }),
        locationState: const AsyncData(DeliveryLocation(
          lat: -36.85,
          lng: 174.76,
          label: 'En route to delivery point',
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Delivery Tracking'), findsOneWidget);
    });

    testWidgets('shows en route status banner', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        deliveryState: const AsyncData({
          'status': 'en_route',
          'delivery_coordinates': {'lat': -36.87, 'lng': 174.78},
          'delivery_fee': 66.60,
        }),
        locationState: const AsyncData(DeliveryLocation(
          lat: -36.85,
          lng: 174.76,
          label: 'En route',
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('En Route'), findsOneWidget);
    });

    testWidgets('shows delivery details', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        deliveryState: const AsyncData({
          'status': 'assigned',
          'delivery_coordinates': {'lat': -36.87, 'lng': 174.78},
          'nautical_miles': 3.5,
          'delivery_fee': 53.00,
          'estimated_delivery_minutes': 23,
          'operator_name': 'Skipper Mike',
          'delivery_location_name': 'Bean Rock',
        }),
        locationState: const AsyncData(DeliveryLocation(
          lat: -36.8406,
          lng: 174.753,
          label: 'At warehouse',
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Bean Rock'), findsOneWidget);
      expect(find.text('3.5 NM'), findsOneWidget);
      expect(find.text('\$53.00 NZD'), findsOneWidget);
      expect(find.text('23 min'), findsOneWidget);
      expect(find.text('Skipper Mike'), findsOneWidget);
    });

    testWidgets('shows status timeline', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        deliveryState: const AsyncData({
          'status': 'pickup',
          'delivery_coordinates': {'lat': -36.87, 'lng': 174.78},
          'delivery_fee': 50.00,
        }),
        locationState: const AsyncData(DeliveryLocation(
          lat: -36.8406,
          lng: 174.753,
          label: 'Departing warehouse',
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Status Timeline'), findsOneWidget);
      expect(find.text('Order Placed'), findsOneWidget);
      expect(find.text('Assigned to Operator'), findsOneWidget);
      expect(find.text('Picking Up'), findsOneWidget);
      expect(find.text('En Route'), findsWidgets);
      expect(find.text('Delivered'), findsOneWidget);
    });

    testWidgets('shows loading state', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            deliveryDetailProvider('test-delivery').overrideWith((ref) async {
              await Future.delayed(const Duration(seconds: 10));
              return {};
            }),
          ],
          child: const MaterialApp(
            home: DeliveryTrackingScreen(deliveryId: 'test-delivery'),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });
  });
}
