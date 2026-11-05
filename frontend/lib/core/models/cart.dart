import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

/// The product snapshot embedded in a cart line (`CartProductSummary`).
class CartProductSummary {
  const CartProductSummary({
    required this.id,
    required this.sku,
    required this.name,
    required this.priceCents,
    required this.effectivePriceCents,
    required this.stockQuantity,
    required this.isActive,
    required this.dangerousGoods,
    this.brand,
    this.images = const [],
    this.salePriceCents,
    this.weightGrams,
  });

  final String id;
  final String sku;
  final String name;
  final String? brand;
  final List<String> images;
  final int priceCents;
  final int? salePriceCents;
  final int effectivePriceCents;
  final int stockQuantity;
  final bool isActive;
  final bool dangerousGoods;
  final int? weightGrams;

  bool get onSale => effectivePriceCents < priceCents;

  factory CartProductSummary.fromJson(Map<String, dynamic> json) => CartProductSummary(
        id: req<String>(json, 'id'),
        sku: req<String>(json, 'sku'),
        name: req<String>(json, 'name'),
        brand: opt<String>(json, 'brand'),
        images: stringList(json, 'images'),
        priceCents: centsFrom(json, 'price_cents'),
        salePriceCents: optionalCentsFrom(json, 'sale_price_cents'),
        effectivePriceCents: centsFrom(json, 'effective_price_cents'),
        stockQuantity: req<int>(json, 'stock_quantity'),
        isActive: req<bool>(json, 'is_active'),
        dangerousGoods: req<bool>(json, 'dangerous_goods'),
        weightGrams: opt<int>(json, 'weight_grams'),
      );
}

/// Human text for a server cart-line issue code.
String cartIssueText(String code, CartProductSummary product) => switch (code) {
      'insufficient_stock' => product.stockQuantity > 0
          ? 'Only ${product.stockQuantity} in stock — reduce the quantity'
          : 'Out of stock',
      'product_unavailable' => 'No longer available — remove it to continue',
      _ => 'This item needs attention ($code)',
    };

/// One cart line (`CartItemResponse`). Prices are server-computed cents.
class CartLine {
  const CartLine({
    required this.id,
    required this.productId,
    required this.quantity,
    required this.unitPriceCents,
    required this.lineTotalCents,
    required this.product,
    this.issues = const [],
    this.createdAt,
  });

  final String id;
  final String productId;
  final int quantity;
  final int unitPriceCents;
  final int lineTotalCents;
  final CartProductSummary product;

  /// Issue codes that block checkout, e.g. `insufficient_stock`.
  final List<String> issues;
  final DateTime? createdAt;

  factory CartLine.fromJson(Map<String, dynamic> json) {
    final created = opt<String>(json, 'created_at');
    return CartLine(
      id: req<String>(json, 'id'),
      productId: req<String>(json, 'product_id'),
      quantity: req<int>(json, 'quantity'),
      unitPriceCents: centsFrom(json, 'unit_price_cents'),
      lineTotalCents: centsFrom(json, 'line_total_cents'),
      product: CartProductSummary.fromJson(reqMap(json, 'product')),
      issues: stringList(json, 'issues'),
      createdAt: created == null ? null : DateTime.parse(created),
    );
  }
}

/// The user's cart (`CartResponse`).
class Cart {
  const Cart({
    required this.currency,
    required this.items,
    required this.subtotalCents,
    required this.itemCount,
    required this.hasIssues,
  });

  static const empty = Cart(
    currency: 'NZD',
    items: [],
    subtotalCents: 0,
    itemCount: 0,
    hasIssues: false,
  );

  final String currency;
  final List<CartLine> items;

  /// Server-computed subtotal; the client never sums prices itself.
  final int subtotalCents;

  /// Total quantity across lines.
  final int itemCount;
  final bool hasIssues;

  bool get isEmpty => items.isEmpty;

  factory Cart.fromJson(Map<String, dynamic> json) => Cart(
        currency: opt<String>(json, 'currency') ?? 'NZD',
        items: [for (final i in mapList(json, 'items')) CartLine.fromJson(i)],
        subtotalCents: centsFrom(json, 'subtotal_cents'),
        itemCount: req<int>(json, 'item_count'),
        hasIssues: req<bool>(json, 'has_issues'),
      );
}
