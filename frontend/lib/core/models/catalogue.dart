/// Catalogue contracts beyond a single product: filter facets, search pages and
/// the public "known to fit" list (`/products/categories`, `/products/brands`,
/// `/search/products`, `/products/{id}/compatibility`).
library;

import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/models/product.dart';

/// `SubCategoryCount`.
class SubCategoryCount {
  const SubCategoryCount({required this.name, required this.count});

  final String name;
  final int count;

  factory SubCategoryCount.fromJson(Map<String, dynamic> json) =>
      SubCategoryCount(name: req<String>(json, 'name'), count: req<int>(json, 'count'));
}

/// `CategoryCount` — a category with its active-product count and sub-categories.
class CategoryCount {
  const CategoryCount({required this.category, required this.count, this.subCategories = const []});

  final String category;
  final int count;
  final List<SubCategoryCount> subCategories;

  factory CategoryCount.fromJson(Map<String, dynamic> json) => CategoryCount(
        category: req<String>(json, 'category'),
        count: req<int>(json, 'count'),
        subCategories: [
          for (final s in mapList(json, 'sub_categories')) SubCategoryCount.fromJson(s),
        ],
      );
}

/// `BrandCount`.
class BrandCount {
  const BrandCount({required this.brand, required this.count});

  final String brand;
  final int count;

  factory BrandCount.fromJson(Map<String, dynamic> json) =>
      BrandCount(brand: req<String>(json, 'brand'), count: req<int>(json, 'count'));
}

/// One facet bucket of a search response. Values are strings, booleans (or
/// `"true"`/`"false"` from the search index) or null.
class FacetValue {
  const FacetValue({required this.value, required this.count});

  final Object? value;
  final int count;

  String get label => '$value';

  factory FacetValue.fromJson(Map<String, dynamic> json) {
    final value = json['value'];
    if (value != null && value is! String && value is! bool) {
      throw FormatException('Field "value": expected string/bool, got ${value.runtimeType}');
    }
    return FacetValue(value: value, count: req<int>(json, 'count'));
  }
}

/// Which engine answered a product search (`SearchResponse.engine`).
enum SearchEngine {
  postgres('postgres'),
  typesense('typesense'),

  /// The search index failed; the server used database search instead.
  postgresFallback('postgres_fallback');

  const SearchEngine(this.wire);

  final String wire;

  static SearchEngine parse(String value) => SearchEngine.values.firstWhere(
        (e) => e.wire == value,
        orElse: () => throw FormatException('Unknown search engine "$value"'),
      );
}

/// `SearchResponse` — a [ProductPage] plus the engine, an optional notice and facets.
class SearchPage extends ProductPage {
  const SearchPage({
    required super.items,
    required super.total,
    required super.offset,
    required super.limit,
    super.vessel,
    required this.engine,
    this.notice,
    this.facets = const {},
  });

  final SearchEngine engine;

  /// Shown to the user when present (e.g. the index fell back, or compatible
  /// results were limited).
  final String? notice;
  final Map<String, List<FacetValue>> facets;

  bool get fellBack => engine == SearchEngine.postgresFallback;

  factory SearchPage.fromJson(Map<String, dynamic> json) {
    final page = ProductPage.fromJson(json);
    final facets = optMap(json, 'facets') ?? const <String, dynamic>{};
    return SearchPage(
      items: page.items,
      total: page.total,
      offset: page.offset,
      limit: page.limit,
      vessel: page.vessel,
      engine: SearchEngine.parse(req<String>(json, 'engine')),
      notice: opt<String>(json, 'notice'),
      facets: {
        for (final e in facets.entries)
          e.key: [
            for (final v in e.value as List) FacetValue.fromJson((v as Map).cast<String, dynamic>()),
          ],
      },
    );
  }
}

/// `KnownFit` — a verified fitment rule shown as "known to fit".
class KnownFit {
  const KnownFit({
    required this.ruleId,
    required this.fitmentType,
    required this.confidenceScore,
    required this.isSynthetic,
    this.vesselMake,
    this.vesselModel,
    this.yearFrom,
    this.yearTo,
    this.engineMake,
    this.engineModel,
    this.engineYearFrom,
    this.engineYearTo,
    this.equipmentCategory,
    this.equipmentMake,
    this.equipmentModel,
    this.dataSource,
    this.notes,
  });

  final String ruleId;
  final String? vesselMake;
  final String? vesselModel;
  final int? yearFrom;
  final int? yearTo;
  final String? engineMake;
  final String? engineModel;
  final int? engineYearFrom;
  final int? engineYearTo;
  final String? equipmentCategory;
  final String? equipmentMake;
  final String? equipmentModel;
  final String fitmentType;
  final double confidenceScore;
  final String? dataSource;
  final bool isSynthetic;
  final String? notes;

  static String? _years(int? from, int? to) {
    if (from == null && to == null) return null;
    if (from != null && to != null) return from == to ? '$from' : '$from–$to';
    return from != null ? '$from on' : 'up to $to';
  }

  static String _join(List<String?> parts) => parts.whereType<String>().where((s) => s.isNotEmpty).join(' ');

  /// Human description, e.g. `Yamaha F150 engines` or `Haines Hunter SF600 (2015–2020)`.
  String get description {
    final out = <String>[];
    if (vesselMake != null) {
      final years = _years(yearFrom, yearTo);
      out.add(_join([vesselMake, vesselModel]) + (years == null ? '' : ' ($years)'));
    }
    if (engineMake != null) {
      final years = _years(engineYearFrom, engineYearTo);
      out.add('${_join([engineMake, engineModel])} engines${years == null ? '' : ' ($years)'}');
    }
    if (equipmentCategory != null || equipmentMake != null) {
      out.add(_join([equipmentMake, equipmentModel, if (equipmentCategory != null) '(${equipmentCategory!.replaceAll('_', ' ')})']));
    }
    return out.isEmpty ? 'Verified fitment' : out.join(' · ');
  }

  factory KnownFit.fromJson(Map<String, dynamic> json) => KnownFit(
        ruleId: req<String>(json, 'rule_id'),
        vesselMake: opt<String>(json, 'vessel_make'),
        vesselModel: opt<String>(json, 'vessel_model'),
        yearFrom: opt<int>(json, 'year_from'),
        yearTo: opt<int>(json, 'year_to'),
        engineMake: opt<String>(json, 'engine_make'),
        engineModel: opt<String>(json, 'engine_model'),
        engineYearFrom: opt<int>(json, 'engine_year_from'),
        engineYearTo: opt<int>(json, 'engine_year_to'),
        equipmentCategory: opt<String>(json, 'equipment_category'),
        equipmentMake: opt<String>(json, 'equipment_make'),
        equipmentModel: opt<String>(json, 'equipment_model'),
        fitmentType: req<String>(json, 'fitment_type'),
        confidenceScore: optDouble(json, 'confidence_score') ??
            (throw const FormatException('Field "confidence_score": missing')),
        dataSource: opt<String>(json, 'data_source'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        notes: opt<String>(json, 'notes'),
      );
}

/// `CompatibilityResponse` for `GET /products/{id}/compatibility`.
class ProductCompatibility {
  const ProductCompatibility({
    required this.productId,
    required this.sku,
    required this.fitmentScope,
    required this.universal,
    this.oemPartNumbers = const [],
    this.knownToFit = const [],
  });

  final String productId;
  final String sku;
  final String fitmentScope;
  final bool universal;
  final List<String> oemPartNumbers;
  final List<KnownFit> knownToFit;

  factory ProductCompatibility.fromJson(Map<String, dynamic> json) => ProductCompatibility(
        productId: req<String>(json, 'product_id'),
        sku: req<String>(json, 'sku'),
        fitmentScope: req<String>(json, 'fitment_scope'),
        universal: req<bool>(json, 'universal'),
        oemPartNumbers: stringList(json, 'oem_part_numbers'),
        knownToFit: [for (final k in mapList(json, 'known_to_fit')) KnownFit.fromJson(k)],
      );
}
