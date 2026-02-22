import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';

void main() {
  group('ProductFilter', () {
    test('default filter has no constraints', () {
      const filter = ProductFilter();

      expect(filter.category, isNull);
      expect(filter.brand, isNull);
      expect(filter.search, isNull);
      expect(filter.vesselId, isNull);
      expect(filter.offset, 0);
      expect(filter.limit, 20);
    });

    test('copyWith creates modified filter', () {
      const filter = ProductFilter();
      final withSearch = filter.copyWith(search: 'anchor', offset: 20);

      expect(withSearch.search, 'anchor');
      expect(withSearch.offset, 20);
      expect(withSearch.limit, 20); // unchanged
      expect(withSearch.category, isNull); // unchanged
    });

    test('copyWith preserves all fields', () {
      const filter = ProductFilter(
        category: 'Filters',
        brand: 'Yamaha',
        vesselId: 'v-001',
        search: 'oil',
        offset: 10,
        limit: 50,
      );

      final modified = filter.copyWith(brand: 'Mercury');

      expect(modified.category, 'Filters'); // preserved
      expect(modified.brand, 'Mercury'); // changed
      expect(modified.vesselId, 'v-001'); // preserved
      expect(modified.search, 'oil'); // preserved
      expect(modified.offset, 10); // preserved
      expect(modified.limit, 50); // preserved
    });
  });
}
