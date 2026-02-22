import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/products/screens/product_detail_screen.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

void main() {
  group('ProductDetailScreen', () {
    Widget buildTestWidget({
      required Product product,
    }) {
      return ProviderScope(
        overrides: [
          productDetailProvider(product.id).overrideWith((ref) async {
            return product;
          }),
          vesselListProvider.overrideWith((ref) async {
            return [];
          }),
        ],
        child: MaterialApp(
          home: ProductDetailScreen(productId: product.id),
        ),
      );
    }

    testWidgets('shows product name and price', (tester) async {
      final product = Product(
        id: 'test-1',
        name: 'Marine Engine Oil',
        sku: 'OIL-001',
        price: 62.90,
        stockQty: 10,
        weightKg: 4.2,
        category: 'Engine Parts',
      );
      await tester.pumpWidget(buildTestWidget(product: product));
      await tester.pumpAndSettle();

      expect(find.text('Marine Engine Oil'), findsOneWidget);
      expect(find.text('\$62.90'), findsOneWidget);
    });

    testWidgets('shows empty image placeholder when no images', (tester) async {
      final product = Product(
        id: 'test-2',
        name: 'No Image Product',
        sku: 'NI-001',
        price: 29.99,
        stockQty: 5,
        weightKg: 1.0,
        category: 'Safety',
      );
      await tester.pumpWidget(buildTestWidget(product: product));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.inventory_2_outlined), findsOneWidget);
    });

    testWidgets('shows PageView when multiple images', (tester) async {
      final product = Product(
        id: 'test-3',
        name: 'Multi Image Product',
        sku: 'MI-001',
        price: 149.99,
        stockQty: 3,
        weightKg: 2.0,
        category: 'Electronics',
        images: [
          'https://example.com/img1.jpg',
          'https://example.com/img2.jpg',
          'https://example.com/img3.jpg',
        ],
      );
      await tester.pumpWidget(buildTestWidget(product: product));
      await tester.pumpAndSettle();

      expect(find.byType(PageView), findsOneWidget);
    });

    testWidgets('shows page indicator dots for multi-image', (tester) async {
      final product = Product(
        id: 'test-4',
        name: 'Gallery Product',
        sku: 'GP-001',
        price: 99.99,
        stockQty: 7,
        weightKg: 0.5,
        category: 'Navigation',
        images: [
          'https://example.com/a.jpg',
          'https://example.com/b.jpg',
        ],
      );
      await tester.pumpWidget(buildTestWidget(product: product));
      await tester.pumpAndSettle();

      // 2 dot indicators for 2 images
      final dots = tester.widgetList<Container>(
        find.byWidgetPredicate((widget) =>
            widget is Container &&
            widget.decoration is BoxDecoration &&
            (widget.decoration as BoxDecoration).shape == BoxShape.circle),
      );
      expect(dots.length, greaterThanOrEqualTo(2));
    });

    testWidgets('shows sale badge when on sale', (tester) async {
      final product = Product(
        id: 'test-5',
        name: 'Sale Item',
        sku: 'SALE-001',
        price: 100.00,
        salePrice: 79.99,
        stockQty: 2,
        weightKg: 1.0,
        category: 'Safety',
      );
      await tester.pumpWidget(buildTestWidget(product: product));
      await tester.pumpAndSettle();

      expect(find.text('SALE'), findsOneWidget);
      expect(find.text('\$79.99'), findsOneWidget);
    });
  });
}
