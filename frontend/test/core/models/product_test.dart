import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/product.dart';

void main() {
  group('Product', () {
    test('fromJson creates Product correctly', () {
      final json = {
        'id': 'prod-001',
        'name': 'Yamaha Oil Filter',
        'description': 'OEM oil filter for Yamaha outboards',
        'brand': 'Yamaha',
        'category': 'Filters',
        'sku': 'YAM-OF-001',
        'price': 29.95,
        'sale_price': null,
        'stock_qty': 42,
        'weight_kg': 0.3,
        'image_url': 'https://example.com/filter.jpg',
        'images': ['https://example.com/filter1.jpg'],
        'is_active': true,
      };

      final product = Product.fromJson(json);

      expect(product.id, 'prod-001');
      expect(product.name, 'Yamaha Oil Filter');
      expect(product.brand, 'Yamaha');
      expect(product.sku, 'YAM-OF-001');
      expect(product.price, 29.95);
      expect(product.salePrice, isNull);
      expect(product.stockQty, 42);
      expect(product.weightKg, 0.3);
    });

    test('effectivePrice returns salePrice when on sale', () {
      final product = Product(
        id: 'p1',
        name: 'Test',
        sku: 'T-001',
        price: 100.0,
        salePrice: 79.95,
        stockQty: 10,
        weightKg: 1.0,
      );

      expect(product.effectivePrice, 79.95);
      expect(product.isOnSale, true);
    });

    test('effectivePrice returns price when not on sale', () {
      final product = Product(
        id: 'p2',
        name: 'Test',
        sku: 'T-002',
        price: 50.0,
        stockQty: 5,
        weightKg: 0.5,
      );

      expect(product.effectivePrice, 50.0);
      expect(product.isOnSale, false);
    });

    test('inStock is true when stockQty > 0', () {
      final inStock = Product(
        id: 'p3',
        name: 'Test',
        sku: 'T-003',
        price: 10.0,
        stockQty: 1,
        weightKg: 0.1,
      );
      final outOfStock = Product(
        id: 'p4',
        name: 'Test',
        sku: 'T-004',
        price: 10.0,
        stockQty: 0,
        weightKg: 0.1,
      );

      expect(inStock.inStock, true);
      expect(outOfStock.inStock, false);
    });

    test('fromJson handles missing optional fields', () {
      final json = {
        'id': 'p5',
        'name': 'Bare Product',
        'sku': 'BP-001',
        'price': 15.0,
      };

      final product = Product.fromJson(json);

      expect(product.brand, isNull);
      expect(product.description, isNull);
      expect(product.salePrice, isNull);
      expect(product.stockQty, 0);
      expect(product.weightKg, 0.0);
      expect(product.images, isEmpty);
      expect(product.isActive, true);
    });
  });
}
