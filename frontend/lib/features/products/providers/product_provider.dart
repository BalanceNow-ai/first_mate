import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/models/product.dart';

/// Search / filter parameters for products.
class ProductFilter {
  final String? category;
  final String? brand;
  final String? vesselId;
  final String? search;
  final int offset;
  final int limit;

  const ProductFilter({
    this.category,
    this.brand,
    this.vesselId,
    this.search,
    this.offset = 0,
    this.limit = 20,
  });

  ProductFilter copyWith({
    String? category,
    String? brand,
    String? vesselId,
    String? search,
    int? offset,
    int? limit,
  }) {
    return ProductFilter(
      category: category ?? this.category,
      brand: brand ?? this.brand,
      vesselId: vesselId ?? this.vesselId,
      search: search ?? this.search,
      offset: offset ?? this.offset,
      limit: limit ?? this.limit,
    );
  }
}

/// Current filter state.
final productFilterProvider = StateProvider<ProductFilter>(
  (ref) => const ProductFilter(),
);

/// Product list based on current filter.
final productListProvider = FutureProvider<List<Product>>((ref) async {
  final filter = ref.watch(productFilterProvider);
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProducts(
    category: filter.category,
    brand: filter.brand,
    vesselId: filter.vesselId,
    search: filter.search,
    offset: filter.offset,
    limit: filter.limit,
  );
});

/// Single product detail.
final productDetailProvider =
    FutureProvider.family<Product, String>((ref, id) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProduct(id);
});

/// Compatibility check result.
final compatibilityProvider = FutureProvider.family<Map<String, dynamic>,
    ({String productId, String vesselId})>((ref, params) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.checkCompatibility(params.productId, params.vesselId);
});
