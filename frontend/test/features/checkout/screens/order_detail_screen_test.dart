import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/checkout/screens/order_detail_screen.dart';

void main() {
  group('OrderDetailScreen', () {
    Widget buildTestWidget({
      required String orderId,
      AsyncValue<Map<String, dynamic>>? orderState,
    }) {
      return ProviderScope(
        overrides: [
          if (orderState != null)
            orderDetailProvider(orderId).overrideWith((ref) async {
              if (orderState is AsyncError) throw orderState.error!;
              return orderState.value!;
            }),
        ],
        child: MaterialApp(
          home: OrderDetailScreen(orderId: orderId),
        ),
      );
    }

    testWidgets('shows Order Details title in app bar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'paid',
          'subtotal': 100.0,
          'shipping_cost': 9.90,
          'total': 109.90,
          'delivery_type': 'courier',
          'items': [],
          'created_at': '2026-01-15T10:30:00Z',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Order Details'), findsOneWidget);
    });

    testWidgets('shows order number from truncated ID', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'pending',
          'subtotal': 50.0,
          'shipping_cost': 9.90,
          'total': 59.90,
          'delivery_type': 'courier',
          'items': [],
          'created_at': '',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Order #ABC12345'), findsOneWidget);
    });

    testWidgets('shows status chip', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'shipped',
          'subtotal': 100.0,
          'shipping_cost': 0.0,
          'total': 100.0,
          'delivery_type': 'courier',
          'items': [],
          'created_at': '2026-02-01T12:00:00Z',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('SHIPPED'), findsOneWidget);
    });

    testWidgets('shows order items', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'paid',
          'subtotal': 125.80,
          'shipping_cost': 9.90,
          'total': 135.70,
          'delivery_type': 'courier',
          'items': [
            {
              'product_id': 'p-1',
              'quantity': 2,
              'unit_price': 62.90,
            },
          ],
          'created_at': '2026-01-20T14:00:00Z',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Items'), findsOneWidget);
      expect(find.text('Product (x2)'), findsOneWidget);
      expect(find.text('\$125.80'), findsOneWidget);
    });

    testWidgets('shows totals section', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'paid',
          'subtotal': 200.0,
          'shipping_cost': 0.0,
          'total': 200.0,
          'delivery_type': 'courier',
          'items': [],
          'created_at': '',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Subtotal'), findsOneWidget);
      expect(find.text('Shipping'), findsOneWidget);
      expect(find.text('Total'), findsOneWidget);
    });

    testWidgets('shows delivery info', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'shipped',
          'subtotal': 100.0,
          'shipping_cost': 9.90,
          'total': 109.90,
          'delivery_type': 'courier',
          'tracking_number': 'NZ123456789',
          'courier': 'NZ Post',
          'items': [],
          'created_at': '',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Delivery'), findsOneWidget);
      expect(find.text('Tracking: NZ123456789'), findsOneWidget);
      expect(find.text('Courier: NZ Post'), findsOneWidget);
    });

    testWidgets('shows Helm Dash delivery label', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'pending',
          'subtotal': 75.0,
          'shipping_cost': 25.0,
          'total': 100.0,
          'delivery_type': 'helm_dash',
          'items': [],
          'created_at': '',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Helm Dash Maritime Delivery'), findsOneWidget);
    });

    testWidgets('shows Click & Collect delivery label', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'pending',
          'subtotal': 50.0,
          'shipping_cost': 0.0,
          'total': 50.0,
          'delivery_type': 'click_and_collect',
          'items': [],
          'created_at': '',
        }),
      ));
      await tester.pumpAndSettle();

      expect(
          find.text('Click & Collect — Westhaven Marina'), findsOneWidget);
    });

    testWidgets('shows error state with retry button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'bad-id',
        orderState:
            AsyncError(Exception('Not found'), StackTrace.current),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Retry'), findsOneWidget);
      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });

    testWidgets('shows formatted date', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'delivered',
          'subtotal': 50.0,
          'shipping_cost': 0.0,
          'total': 50.0,
          'delivery_type': 'courier',
          'items': [],
          'created_at': '2026-02-15T09:00:00Z',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Placed 15/2/2026'), findsOneWidget);
    });
  });
}
