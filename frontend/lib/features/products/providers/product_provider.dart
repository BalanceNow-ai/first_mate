import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/catalogue.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/products/data/catalogue_api.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

export 'package:helm_marine/features/products/data/catalogue_api.dart' show ProductQuery, ProductSort;

/// Products per page (and per infinite-scroll step).
const productPageSize = 24;

/// The shop's current filter. Reset when the user changes.
final productQueryProvider = NotifierProvider<ProductQueryNotifier, ProductQuery>(ProductQueryNotifier.new);

class ProductQueryNotifier extends Notifier<ProductQuery> {
  @override
  ProductQuery build() {
    ref.watch(currentUserIdProvider);
    return const ProductQuery();
  }

  void set(ProductQuery query) => state = query;

  void update(ProductQuery Function(ProductQuery) change) => state = change(state);
}

/// Whether the shop evaluates fitment against the shopping vessel.
final useVesselFitmentProvider =
    NotifierProvider<_BoolNotifier, bool>(() => _BoolNotifier(initial: true));

class _BoolNotifier extends Notifier<bool> {
  _BoolNotifier({required this.initial});

  final bool initial;

  @override
  bool build() {
    ref.watch(currentUserIdProvider);
    return initial;
  }

  void set(bool value) => state = value;
}

/// The vessel id sent with catalogue requests (null = no fitment evaluation).
final fitmentVesselIdProvider = Provider<String?>((ref) {
  if (!ref.watch(useVesselFitmentProvider)) return null;
  return ref.watch(shoppingVesselProvider)?.id;
});

/// A loaded, growable list of products for the current query.
class ProductFeed {
  const ProductFeed({
    required this.query,
    required this.items,
    required this.total,
    this.vessel,
    this.engine,
    this.notice,
    this.loadingMore = false,
    this.loadMoreError,
  });

  final ProductQuery query;
  final List<Product> items;
  final int total;

  /// The vessel fitment was evaluated against (server's label).
  final VesselRef? vessel;

  /// Set for text searches (`GET /search/products`).
  final SearchEngine? engine;
  final String? notice;
  final bool loadingMore;
  final Object? loadMoreError;

  bool get hasMore => items.length < total;

  ProductFeed copyWith({
    List<Product>? items,
    int? total,
    bool? loadingMore,
    Object? loadMoreError,
    bool clearError = false,
  }) =>
      ProductFeed(
        query: query,
        items: items ?? this.items,
        total: total ?? this.total,
        vessel: vessel,
        engine: engine,
        notice: notice,
        loadingMore: loadingMore ?? this.loadingMore,
        loadMoreError: clearError ? null : (loadMoreError ?? this.loadMoreError),
      );
}

/// Products for [productQueryProvider], with server-evaluated fitment for the
/// shopping vessel. A text query uses `GET /search/products`; otherwise
/// `GET /products/`. [ProductFeedNotifier.loadMore] appends the next page.
final productFeedProvider = AsyncNotifierProvider<ProductFeedNotifier, ProductFeed>(ProductFeedNotifier.new);

class ProductFeedNotifier extends AsyncNotifier<ProductFeed> {
  int _generation = 0;

  Future<ProductPage> _page(ProductQuery query, String? vesselId, int offset) {
    final api = ref.read(catalogueApiProvider);
    return query.isSearch
        ? api.search(query, vesselId: vesselId, offset: offset, limit: productPageSize)
        : api.listProducts(query, vesselId: vesselId, offset: offset, limit: productPageSize);
  }

  static ProductFeed _feed(ProductQuery query, ProductPage page) => ProductFeed(
        query: query,
        items: page.items,
        total: page.total,
        vessel: page.vessel,
        engine: page is SearchPage ? page.engine : null,
        notice: page is SearchPage ? page.notice : null,
      );

  @override
  Future<ProductFeed> build() async {
    ref.watch(catalogueApiProvider);
    final query = ref.watch(productQueryProvider);
    final vesselId = ref.watch(fitmentVesselIdProvider);
    // A rebuild invalidates any in-flight "load more" for the previous query.
    _generation++;
    return _feed(query, await _page(query, vesselId, 0));
  }

  /// Loads the next page (no-op while loading or when everything is loaded).
  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || current.loadingMore || !current.hasMore || state.isLoading) return;
    final generation = _generation;
    state = AsyncData(current.copyWith(loadingMore: true, clearError: true));
    try {
      final page = await _page(current.query, ref.read(fitmentVesselIdProvider), current.items.length);
      if (generation != _generation || !ref.mounted) return;
      state = AsyncData(current.copyWith(
        items: [...current.items, ...page.items],
        total: page.total,
        loadingMore: false,
        clearError: true,
      ));
    } catch (e) {
      if (generation != _generation || !ref.mounted) return;
      state = AsyncData(current.copyWith(loadingMore: false, loadMoreError: e));
    }
  }
}

/// Category facets (with sub-categories) for the filter sheet.
final productCategoriesProvider = FutureProvider.autoDispose<List<CategoryCount>>((ref) {
  return ref.watch(catalogueApiProvider).categories();
});

/// Brand facets for the filter sheet.
final productBrandsProvider = FutureProvider.autoDispose<List<BrandCount>>((ref) {
  return ref.watch(catalogueApiProvider).brands();
});

/// One product, with fitment for the shopping vessel when there is one.
final productDetailProvider = FutureProvider.autoDispose.family<Product, String>((ref, id) {
  final api = ref.watch(catalogueApiProvider);
  return api.getProduct(id, vesselId: ref.watch(fitmentVesselIdProvider));
});

/// The public "known to fit" list for a product.
final productCompatibilityProvider =
    FutureProvider.autoDispose.family<ProductCompatibility, String>((ref, id) {
  return ref.watch(catalogueApiProvider).compatibility(id);
});
