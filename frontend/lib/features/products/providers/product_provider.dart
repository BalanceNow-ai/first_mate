import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

/// Catalogue search / filter parameters.
class ProductFilter {
  const ProductFilter({
    this.category,
    this.search,
    this.onSale = false,
    this.inStockOnly = false,
    this.offset = 0,
    this.limit = 20,
  });

  final String? category;
  final String? search;
  final bool onSale;
  final bool inStockOnly;
  final int offset;
  final int limit;

  ProductFilter copyWith({
    String? category,
    String? search,
    bool? onSale,
    bool? inStockOnly,
    int? offset,
    bool clearCategory = false,
    bool clearSearch = false,
  }) {
    return ProductFilter(
      category: clearCategory ? null : (category ?? this.category),
      search: clearSearch ? null : (search ?? this.search),
      onSale: onSale ?? this.onSale,
      inStockOnly: inStockOnly ?? this.inStockOnly,
      // Any filter change returns to the first page unless an offset is given.
      offset: offset ?? 0,
      limit: limit,
    );
  }
}

final productFilterProvider =
    NotifierProvider<ProductFilterNotifier, ProductFilter>(ProductFilterNotifier.new);

class ProductFilterNotifier extends Notifier<ProductFilter> {
  @override
  ProductFilter build() => const ProductFilter();

  void update(ProductFilter Function(ProductFilter) change) => state = change(state);
}

/// Whether the shop evaluates fitment against the shopping vessel.
final useVesselFitmentProvider =
    NotifierProvider<_BoolNotifier, bool>(() => _BoolNotifier(initial: true));

class _BoolNotifier extends Notifier<bool> {
  _BoolNotifier({required this.initial});

  final bool initial;

  @override
  bool build() => initial;

  void set(bool value) => state = value;
}

/// The vessel id sent with catalogue requests (null = no fitment evaluation).
final fitmentVesselIdProvider = Provider<String?>((ref) {
  if (!ref.watch(useVesselFitmentProvider)) return null;
  return ref.watch(shoppingVesselProvider)?.id;
});

/// A page of products for the current filter, with server-evaluated fitment
/// for the shopping vessel.
final productListProvider = FutureProvider.autoDispose<ProductPage>((ref) {
  final api = ref.watch(userApiProvider);
  final filter = ref.watch(productFilterProvider);
  return api.getProducts(
    category: filter.category,
    search: filter.search,
    vesselId: ref.watch(fitmentVesselIdProvider),
    onSale: filter.onSale,
    inStockOnly: filter.inStockOnly,
    offset: filter.offset,
    limit: filter.limit,
  );
});

/// Product categories offered as filter chips.
final productCategoriesProvider = FutureProvider.autoDispose<List<String>>((ref) {
  return ref.watch(userApiProvider).getProductCategories();
});

/// One product, with fitment for the shopping vessel when there is one.
final productDetailProvider = FutureProvider.autoDispose.family<Product, String>((ref, id) {
  final api = ref.watch(userApiProvider);
  return api.getProduct(id, vesselId: ref.watch(fitmentVesselIdProvider));
});
