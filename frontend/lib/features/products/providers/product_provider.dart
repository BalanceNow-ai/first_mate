import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/models/product.dart';

/// Search / filter parameters for products.
class ProductFilter {
  final String? category;
  final String? brand;
  final String? vesselId;
  final String? search;
  final bool onSale;
  final bool vesselCompatible;
  final int offset;
  final int limit;

  const ProductFilter({
    this.category,
    this.brand,
    this.vesselId,
    this.search,
    this.onSale = false,
    this.vesselCompatible = false,
    this.offset = 0,
    this.limit = 20,
  });

  ProductFilter copyWith({
    String? category,
    String? brand,
    String? vesselId,
    String? search,
    bool? onSale,
    bool? vesselCompatible,
    int? offset,
    int? limit,
    bool clearCategory = false,
    bool clearBrand = false,
    bool clearSearch = false,
  }) {
    return ProductFilter(
      category: clearCategory ? null : (category ?? this.category),
      brand: clearBrand ? null : (brand ?? this.brand),
      vesselId: vesselId ?? this.vesselId,
      search: clearSearch ? null : (search ?? this.search),
      onSale: onSale ?? this.onSale,
      vesselCompatible: vesselCompatible ?? this.vesselCompatible,
      offset: offset ?? this.offset,
      limit: limit ?? this.limit,
    );
  }
}

/// Current filter state.
final productFilterProvider = StateProvider<ProductFilter>(
  (ref) => const ProductFilter(),
);

/// Available categories from backend.
final productCategoriesProvider =
    FutureProvider.autoDispose<List<String>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProductCategories();
});

/// Available brands from backend.
final productBrandsProvider =
    FutureProvider.autoDispose<List<String>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProductBrands();
});

/// Product list based on current filter.
final productListProvider =
    FutureProvider.autoDispose<List<Product>>((ref) async {
  final filter = ref.watch(productFilterProvider);
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProducts(
    category: filter.category,
    brand: filter.brand,
    vesselId: filter.vesselCompatible ? filter.vesselId : null,
    search: filter.search,
    onSale: filter.onSale ? true : null,
    offset: filter.offset,
    limit: filter.limit,
  );
});

/// Single product detail.
final productDetailProvider =
    FutureProvider.autoDispose.family<Product, String>((ref, id) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getProduct(id);
});

/// Compatibility check result.
final compatibilityProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, ({String productId, String vesselId})>(
        (ref, params) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.checkCompatibility(params.productId, params.vesselId);
});
