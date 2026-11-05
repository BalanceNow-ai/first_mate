import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/catalogue.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/products/data/api_call.dart';

/// Sort orders accepted by `GET /products/` and `GET /search/products`.
enum ProductSort {
  relevance('relevance', 'Best match'),
  name('name', 'Name'),
  priceAsc('price_asc', 'Price: low to high'),
  priceDesc('price_desc', 'Price: high to low'),
  newest('newest', 'Newest');

  const ProductSort(this.wire, this.label);

  final String wire;
  final String label;

  static ProductSort? tryParse(String? value) {
    for (final s in values) {
      if (s.wire == value) return s;
    }
    return null;
  }
}

/// The catalogue filter — the query names of `GET /products/` exactly.
class ProductQuery {
  const ProductQuery({
    this.q,
    this.category,
    this.subCategory,
    this.brand,
    this.minPriceCents,
    this.maxPriceCents,
    this.inStock = false,
    this.onSale = false,
    this.partRole,
    this.compatibleOnly = false,
    this.sort,
  });

  final String? q;
  final String? category;
  final String? subCategory;
  final String? brand;
  final int? minPriceCents;
  final int? maxPriceCents;
  final bool inStock;
  final bool onSale;
  final String? partRole;

  /// Only verified fits / universal parts for the vessel (requires a vessel).
  final bool compatibleOnly;

  /// Null = the endpoint's default (`name` for browse, `relevance` for search).
  final ProductSort? sort;

  bool get isSearch => q != null && q!.trim().isNotEmpty;

  bool get hasFilters =>
      category != null ||
      subCategory != null ||
      brand != null ||
      minPriceCents != null ||
      maxPriceCents != null ||
      inStock ||
      onSale ||
      partRole != null;

  static const _unset = Object();

  ProductQuery copyWith({
    Object? q = _unset,
    Object? category = _unset,
    Object? subCategory = _unset,
    Object? brand = _unset,
    Object? minPriceCents = _unset,
    Object? maxPriceCents = _unset,
    bool? inStock,
    bool? onSale,
    Object? partRole = _unset,
    bool? compatibleOnly,
    Object? sort = _unset,
  }) =>
      ProductQuery(
        q: q == _unset ? this.q : q as String?,
        category: category == _unset ? this.category : category as String?,
        subCategory: subCategory == _unset ? this.subCategory : subCategory as String?,
        brand: brand == _unset ? this.brand : brand as String?,
        minPriceCents: minPriceCents == _unset ? this.minPriceCents : minPriceCents as int?,
        maxPriceCents: maxPriceCents == _unset ? this.maxPriceCents : maxPriceCents as int?,
        inStock: inStock ?? this.inStock,
        onSale: onSale ?? this.onSale,
        partRole: partRole == _unset ? this.partRole : partRole as String?,
        compatibleOnly: compatibleOnly ?? this.compatibleOnly,
        sort: sort == _unset ? this.sort : sort as ProductSort?,
      );

  /// Parses the shop's deep-link query (`/products?q=…&part_role=…&compatible_only=true`).
  factory ProductQuery.fromUri(Map<String, String> params) {
    String? s(String key) {
      final v = params[key]?.trim();
      return v == null || v.isEmpty ? null : v;
    }

    return ProductQuery(
      q: s('q'),
      category: s('category'),
      subCategory: s('sub_category'),
      brand: s('brand'),
      minPriceCents: int.tryParse(params['min_price_cents'] ?? ''),
      maxPriceCents: int.tryParse(params['max_price_cents'] ?? ''),
      inStock: params['in_stock'] == 'true',
      onSale: params['on_sale'] == 'true',
      partRole: s('part_role'),
      compatibleOnly: params['compatible_only'] == 'true',
      sort: ProductSort.tryParse(params['sort']),
    );
  }

  /// Query parameters for a page request. `compatible_only` is only sent with
  /// a vessel (the server refuses it otherwise).
  Map<String, dynamic> toQueryParameters({String? vesselId, int offset = 0, int limit = 24}) => {
        if (isSearch) 'q': q!.trim(),
        'category': ?category,
        'sub_category': ?subCategory,
        'brand': ?brand,
        'min_price_cents': ?minPriceCents,
        'max_price_cents': ?maxPriceCents,
        if (inStock) 'in_stock': true,
        if (onSale) 'on_sale': true,
        'part_role': ?partRole,
        'vessel_id': ?vesselId,
        if (compatibleOnly && vesselId != null) 'compatible_only': true,
        if (sort != null) 'sort': sort!.wire,
        'offset': offset,
        'limit': limit,
      };

  @override
  bool operator ==(Object other) =>
      other is ProductQuery &&
      other.q == q &&
      other.category == category &&
      other.subCategory == subCategory &&
      other.brand == brand &&
      other.minPriceCents == minPriceCents &&
      other.maxPriceCents == maxPriceCents &&
      other.inStock == inStock &&
      other.onSale == onSale &&
      other.partRole == partRole &&
      other.compatibleOnly == compatibleOnly &&
      other.sort == sort;

  @override
  int get hashCode => Object.hash(q, category, subCategory, brand, minPriceCents, maxPriceCents, inStock,
      onSale, partRole, compatibleOnly, sort);
}

/// Catalogue API scoped to the signed-in user (fitment for their vessels).
final catalogueApiProvider = Provider<CatalogueApi>((ref) {
  ref.watch(currentUserIdProvider);
  return CatalogueApi(ref.watch(dioProvider));
});

/// Typed access to `/products` and `/search/products`.
class CatalogueApi {
  CatalogueApi(this._dio);

  final Dio _dio;

  /// `GET /products/` — browse with filters.
  Future<ProductPage> listProducts(ProductQuery query, {String? vesselId, int offset = 0, int limit = 24}) =>
      apiCall(
        () => _dio.get('/products/',
            queryParameters: query.toQueryParameters(vesselId: vesselId, offset: offset, limit: limit)),
        (d) => ProductPage.fromJson(asMap(d)),
      );

  /// `GET /search/products` — text search; reports the engine and any notice.
  Future<SearchPage> search(ProductQuery query, {String? vesselId, int offset = 0, int limit = 24}) => apiCall(
        () => _dio.get('/search/products',
            queryParameters: query.toQueryParameters(vesselId: vesselId, offset: offset, limit: limit)),
        (d) => SearchPage.fromJson(asMap(d)),
      );

  Future<Product> getProduct(String id, {String? vesselId}) => apiCall(
        () => _dio.get('/products/$id', queryParameters: {'vessel_id': ?vesselId}),
        (d) => Product.fromJson(asMap(d)),
      );

  /// `GET /products/{id}/compatibility` — the public "known to fit" list.
  Future<ProductCompatibility> compatibility(String id) => apiCall(
        () => _dio.get('/products/$id/compatibility'),
        (d) => ProductCompatibility.fromJson(asMap(d)),
      );

  Future<List<CategoryCount>> categories() => apiCall(
        () => _dio.get('/products/categories'),
        (d) => [for (final c in asList(d)) CategoryCount.fromJson(c)],
      );

  Future<List<BrandCount>> brands() => apiCall(
        () => _dio.get('/products/brands'),
        (d) => [for (final b in asList(d)) BrandCount.fromJson(b)],
      );
}
