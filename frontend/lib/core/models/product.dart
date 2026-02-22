class Product {
  final String id;
  final String name;
  final String? description;
  final String? brand;
  final String? category;
  final String sku;
  final double price;
  final double? salePrice;
  final int stockQty;
  final double weightKg;
  final String? imageUrl;
  final List<String> images;
  final bool isActive;

  Product({
    required this.id,
    required this.name,
    this.description,
    this.brand,
    this.category,
    required this.sku,
    required this.price,
    this.salePrice,
    required this.stockQty,
    required this.weightKg,
    this.imageUrl,
    this.images = const [],
    this.isActive = true,
  });

  double get effectivePrice => salePrice ?? price;

  bool get isOnSale => salePrice != null && salePrice! < price;

  bool get inStock => stockQty > 0;

  factory Product.fromJson(Map<String, dynamic> json) {
    return Product(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      brand: json['brand'] as String?,
      category: json['category'] as String?,
      sku: json['sku'] as String,
      price: (json['price'] as num).toDouble(),
      salePrice: (json['sale_price'] as num?)?.toDouble(),
      stockQty: json['stock_qty'] as int? ?? 0,
      weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 0.0,
      imageUrl: json['image_url'] as String?,
      images: (json['images'] as List<dynamic>?)
              ?.map((e) => e as String)
              .toList() ??
          [],
      isActive: json['is_active'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'description': description,
        'brand': brand,
        'category': category,
        'sku': sku,
        'price': price,
        'sale_price': salePrice,
        'stock_qty': stockQty,
        'weight_kg': weightKg,
        'image_url': imageUrl,
        'images': images,
        'is_active': isActive,
      };
}
