import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

/// Outcome of the server's central fitment evaluation.
enum FitmentStatus {
  verifiedFit('verified_fit'),
  verifiedMismatch('verified_mismatch'),
  unknown('unknown'),
  universal('universal');

  const FitmentStatus(this.wire);

  final String wire;

  /// Unrecognised values are treated as [unknown] — never as a fit.
  static FitmentStatus parse(String? value) => FitmentStatus.values.firstWhere(
        (s) => s.wire == value,
        orElse: () => FitmentStatus.unknown,
      );

  /// Only a verified fit or a verified-universal part may be shown as fitting.
  bool get fits => this == verifiedFit || this == universal;
}

/// `FitmentResult` for one product and one vessel.
class Fitment {
  const Fitment({
    required this.status,
    required this.message,
    this.vesselId,
    this.reasons = const [],
  });

  final FitmentStatus status;
  final String message;
  final String? vesselId;
  final List<String> reasons;

  factory Fitment.fromJson(Map<String, dynamic> json) => Fitment(
        status: FitmentStatus.parse(req<String>(json, 'status')),
        message: req<String>(json, 'message'),
        vesselId: opt<String>(json, 'vessel_id'),
        reasons: stringList(json, 'reasons'),
      );
}

/// A catalogue product (`ProductResponse`). Prices are integer NZD cents.
class Product {
  const Product({
    required this.id,
    required this.sku,
    required this.name,
    required this.category,
    required this.currency,
    required this.priceCents,
    required this.effectivePriceCents,
    required this.onSale,
    required this.stockQuantity,
    required this.inStock,
    required this.fitmentScope,
    required this.dangerousGoods,
    required this.isActive,
    this.description,
    this.brand,
    this.subCategory,
    this.salePriceCents,
    this.weightGrams,
    this.images = const [],
    this.specifications,
    this.oemPartNumbers = const [],
    this.partRole,
    this.fitment,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String sku;
  final String name;
  final String? description;
  final String? brand;
  final String category;
  final String? subCategory;
  final String currency;
  final int priceCents;
  final int? salePriceCents;

  /// The price the customer pays (server-computed; equals the cart unit price).
  final int effectivePriceCents;
  final bool onSale;
  final int stockQuantity;
  final bool inStock;
  final int? weightGrams;
  final List<String> images;
  final Map<String, dynamic>? specifications;
  final List<String> oemPartNumbers;
  final String? partRole;

  /// `universal` / `specific` / `unspecified`.
  final String fitmentScope;
  final bool dangerousGoods;
  final bool isActive;
  final Fitment? fitment;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  String? get primaryImage => images.isEmpty ? null : images.first;

  String get priceText => formatCents(effectivePriceCents, currency: currency);

  /// The undiscounted price, shown struck through when [onSale].
  String get regularPriceText => formatCents(priceCents, currency: currency);

  factory Product.fromJson(Map<String, dynamic> json) {
    final fitment = optMap(json, 'fitment');
    final created = opt<String>(json, 'created_at');
    final updated = opt<String>(json, 'updated_at');
    return Product(
      id: req<String>(json, 'id'),
      sku: req<String>(json, 'sku'),
      name: req<String>(json, 'name'),
      description: opt<String>(json, 'description'),
      brand: opt<String>(json, 'brand'),
      category: req<String>(json, 'category'),
      subCategory: opt<String>(json, 'sub_category'),
      currency: opt<String>(json, 'currency') ?? 'NZD',
      priceCents: centsFrom(json, 'price_cents'),
      salePriceCents: optionalCentsFrom(json, 'sale_price_cents'),
      effectivePriceCents: centsFrom(json, 'effective_price_cents'),
      onSale: req<bool>(json, 'on_sale'),
      stockQuantity: req<int>(json, 'stock_quantity'),
      inStock: req<bool>(json, 'in_stock'),
      weightGrams: opt<int>(json, 'weight_grams'),
      images: stringList(json, 'images'),
      specifications: optMap(json, 'specifications'),
      oemPartNumbers: stringList(json, 'oem_part_numbers'),
      partRole: opt<String>(json, 'part_role'),
      fitmentScope: req<String>(json, 'fitment_scope'),
      dangerousGoods: req<bool>(json, 'dangerous_goods'),
      isActive: req<bool>(json, 'is_active'),
      fitment: fitment == null ? null : Fitment.fromJson(fitment),
      createdAt: created == null ? null : DateTime.parse(created),
      updatedAt: updated == null ? null : DateTime.parse(updated),
    );
  }
}

/// The vessel a product list was evaluated against.
class VesselRef {
  const VesselRef({required this.id, required this.label});

  final String id;
  final String label;

  factory VesselRef.fromJson(Map<String, dynamic> json) =>
      VesselRef(id: req<String>(json, 'id'), label: req<String>(json, 'label'));
}

/// A page of products: `{"items", "total", "offset", "limit", "vessel"}`.
class ProductPage {
  const ProductPage({
    required this.items,
    required this.total,
    required this.offset,
    required this.limit,
    this.vessel,
  });

  final List<Product> items;
  final int total;
  final int offset;
  final int limit;
  final VesselRef? vessel;

  bool get hasMore => offset + items.length < total;

  factory ProductPage.fromJson(Map<String, dynamic> json) {
    final vessel = optMap(json, 'vessel');
    return ProductPage(
      items: [for (final p in mapList(json, 'items')) Product.fromJson(p)],
      total: req<int>(json, 'total'),
      offset: req<int>(json, 'offset'),
      limit: req<int>(json, 'limit'),
      vessel: vessel == null ? null : VesselRef.fromJson(vessel),
    );
  }
}
