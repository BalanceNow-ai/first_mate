import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/checkout/screens/order_detail_screen.dart';

import '../../../helpers/fakes.dart';

void main() {
  group('OrderDetailScreen', () {
    Widget buildTestWidget({
      required String orderId,
      AsyncValue<Map<String, dynamic>>? orderState,
    }) {
      return ProviderScope(
        overrides: [
          ...baseTestOverrides(),
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
          'subtotal_cents': 10000,
          'shipping_cents': 990,
          'total_cents': 10990,
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
          'subtotal_cents': 5000,
          'shipping_cents': 990,
          'total_cents': 5990,
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
          'subtotal_cents': 10000,
          'shipping_cents': 0,
          'total_cents': 10000,
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
          'subtotal_cents': 12580,
          'shipping_cents': 990,
          'total_cents': 13570,
          'delivery_type': 'courier',
          'items': [
            {
              'product_id': 'p-1',
              'quantity': 2,
              'unit_price_cents': 6290,
              'line_total_cents': 12580,
            },
          ],
          'created_at': '2026-01-20T14:00:00Z',
        }),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Items'), findsOneWidget);
      expect(find.text('Product (x2)'), findsOneWidget);
      // Line total and subtotal (both server-provided cents).
      expect(find.text('\$125.80'), findsNWidgets(2));
    });

    testWidgets('shows totals section', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        orderId: 'abc12345-6789-0000-0000-000000000000',
        orderState: const AsyncData({
          'id': 'abc12345-6789-0000-0000-000000000000',
          'status': 'paid',
          'subtotal_cents': 20000,
          'shipping_cents': 0,
          'total_cents': 20000,
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
          'subtotal_cents': 10000,
          'shipping_cents': 990,
          'total_cents': 10990,
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
          'subtotal_cents': 7500,
          'shipping_cents': 2500,
          'total_cents': 10000,
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
          'subtotal_cents': 5000,
          'shipping_cents': 0,
          'total_cents': 5000,
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
          'subtotal_cents': 5000,
          'shipping_cents': 0,
          'total_cents': 5000,
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
