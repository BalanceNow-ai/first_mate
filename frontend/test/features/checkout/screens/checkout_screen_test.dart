import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';
import 'package:helm_marine/features/checkout/screens/checkout_screen.dart';

void main() {
  group('CheckoutScreen', () {
    Widget buildTestWidget({
      AsyncValue<Map<String, dynamic>>? cartState,
    }) {
      return ProviderScope(
        overrides: [
          if (cartState != null)
            cartProvider.overrideWith((ref) async {
              if (cartState is AsyncError) throw cartState.error!;
              return cartState.value!;
            }),
        ],
        child: const MaterialApp(
          home: CheckoutScreen(),
        ),
      );
    }

    testWidgets('shows Checkout title in app bar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 0.0,
          'item_count': 0,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Checkout'), findsOneWidget);
    });

    testWidgets('shows step indicators', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 100.0,
          'item_count': 2,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Shipping'), findsOneWidget);
      expect(find.text('Payment'), findsOneWidget);
      expect(find.text('Confirm'), findsOneWidget);
    });

    testWidgets('shows delivery method options', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 100.0,
          'item_count': 2,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Standard Shipping'), findsOneWidget);
      expect(find.text('Helm Dash'), findsOneWidget);
      expect(find.text('Click & Collect'), findsOneWidget);
    });

    testWidgets('shows Delivery Method heading', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 200.0,
          'item_count': 3,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Delivery Method'), findsOneWidget);
    });

    testWidgets('shows continue to payment button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 100.0,
          'item_count': 1,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    testWidgets('shows shipping address form when courier selected',
        (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 100.0,
          'item_count': 1,
        }),
      ));
      await tester.pumpAndSettle();

      // Courier is selected by default
      expect(find.text('Shipping Address'), findsOneWidget);
      expect(find.text('Full Name'), findsOneWidget);
      expect(find.text('Address Line 1'), findsOneWidget);
      expect(find.text('City'), findsOneWidget);
      expect(find.text('Postcode'), findsOneWidget);
    });

    testWidgets('shows order summary with cart data', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 250.0,
          'item_count': 5,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Order Summary'), findsOneWidget);
      expect(find.text('5 items'), findsOneWidget);
      expect(find.text('\$250.00'), findsOneWidget);
      expect(find.text('FREE'), findsOneWidget); // Free shipping over $150
    });

    testWidgets('shows shipping cost under $150', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 80.0,
          'item_count': 1,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('\$9.90'), findsOneWidget);
    });

    testWidgets('has PageView for step navigation', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        cartState: const AsyncData({
          'items': [],
          'subtotal': 100.0,
          'item_count': 1,
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.byType(PageView), findsOneWidget);
    });
  });
}
