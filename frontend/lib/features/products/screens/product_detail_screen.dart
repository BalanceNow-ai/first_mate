import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:photo_view/photo_view.dart';
import 'package:photo_view/photo_view_gallery.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class ProductDetailScreen extends ConsumerStatefulWidget {
  final String productId;

  const ProductDetailScreen({super.key, required this.productId});

  @override
  ConsumerState<ProductDetailScreen> createState() =>
      _ProductDetailScreenState();
}

class _ProductDetailScreenState extends ConsumerState<ProductDetailScreen> {
  int _quantity = 1;
  bool _addingToCart = false;
  int _currentImagePage = 0;

  Future<void> _addToCart() async {
    setState(() => _addingToCart = true);
    try {
      final apiService = ref.read(apiServiceProvider);
      await apiService.addToCart(widget.productId, quantity: _quantity);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Added to cart'),
            backgroundColor: HelmTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to add to cart: $e'),
            backgroundColor: HelmTheme.error,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _addingToCart = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final productState = ref.watch(productDetailProvider(widget.productId));
    final vesselsState = ref.watch(vesselListProvider);

    return Scaffold(
      appBar: AppBar(
        title: productState.whenOrNull(data: (p) => Text(p.name)) ??
            const Text('Product'),
      ),
      bottomNavigationBar: productState.whenOrNull(
        data: (product) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                // Quantity selector
                Container(
                  decoration: BoxDecoration(
                    border: Border.all(color: Colors.grey[300]!),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.remove, size: 18),
                        tooltip: 'Decrease quantity',
                        onPressed: _quantity > 1
                            ? () => setState(() => _quantity--)
                            : null,
                      ),
                      Text('$_quantity',
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                      IconButton(
                        icon: const Icon(Icons.add, size: 18),
                        tooltip: 'Increase quantity',
                        onPressed: () => setState(() => _quantity++),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: ElevatedButton(
                    onPressed: product.inStock && !_addingToCart
                        ? _addToCart
                        : null,
                    child: _addingToCart
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(product.inStock
                            ? 'Add to Cart — \$${(product.effectivePrice * _quantity).toStringAsFixed(2)}'
                            : 'Out of Stock'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      body: productState.when(
        data: (product) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Image Gallery
            _ProductImageGallery(
              images: product.images,
              fallbackUrl: product.imageUrl,
              currentPage: _currentImagePage,
              onPageChanged: (page) =>
                  setState(() => _currentImagePage = page),
            ),
            const SizedBox(height: 16),

            // Brand
            if (product.brand != null)
              Text(
                product.brand!,
                style: TextStyle(
                  fontSize: 14,
                  color: Colors.grey[600],
                  fontWeight: FontWeight.w500,
                ),
              ),

            // Name
            Text(
              product.name,
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),

            // Price
            Row(
              children: [
                if (product.isOnSale) ...[
                  Text(
                    '\$${product.price.toStringAsFixed(2)}',
                    style: TextStyle(
                      fontSize: 16,
                      color: Colors.grey[500],
                      decoration: TextDecoration.lineThrough,
                    ),
                  ),
                  const SizedBox(width: 8),
                ],
                Text(
                  '\$${product.effectivePrice.toStringAsFixed(2)}',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                    color: product.isOnSale ? HelmTheme.error : HelmTheme.primary,
                  ),
                ),
                if (product.isOnSale) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: HelmTheme.error.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      'SALE',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: HelmTheme.error,
                      ),
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 8),

            // Stock status
            Row(
              children: [
                Icon(
                  product.inStock ? Icons.check_circle : Icons.cancel,
                  size: 16,
                  color: product.inStock ? HelmTheme.success : HelmTheme.error,
                ),
                const SizedBox(width: 4),
                Text(
                  product.inStock
                      ? '${product.stockQty} in stock'
                      : 'Out of stock',
                  style: TextStyle(
                    color: product.inStock ? HelmTheme.success : HelmTheme.error,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text('SKU: ${product.sku}',
                style: TextStyle(color: Colors.grey[500], fontSize: 12)),
            const SizedBox(height: 16),

            // Compatibility check
            vesselsState.whenOrNull(
              data: (vessels) {
                if (vessels.isEmpty) return const SizedBox.shrink();
                final primary = vessels.where((v) => v.isPrimary).firstOrNull ??
                    vessels.first;
                return _CompatibilityBanner(
                  productId: widget.productId,
                  vesselId: primary.id,
                  vesselName: primary.name,
                );
              },
            ) ??
                const SizedBox.shrink(),
            const SizedBox(height: 16),

            // Description
            if (product.description != null) ...[
              Text(
                'Description',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Text(product.description!),
            ],
          ],
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(child: Text('Error: $error')),
      ),
    );
  }
}

class _ProductImageGallery extends StatelessWidget {
  final List<String> images;
  final String? fallbackUrl;
  final int currentPage;
  final ValueChanged<int> onPageChanged;

  const _ProductImageGallery({
    required this.images,
    this.fallbackUrl,
    required this.currentPage,
    required this.onPageChanged,
  });

  List<String> get _allImages {
    if (images.isNotEmpty) return images;
    if (fallbackUrl != null) return [fallbackUrl!];
    return [];
  }

  @override
  Widget build(BuildContext context) {
    final imageUrls = _allImages;

    if (imageUrls.isEmpty) {
      return Container(
        height: 250,
        decoration: BoxDecoration(
          color: Colors.grey[100],
          borderRadius: BorderRadius.circular(16),
        ),
        child: const Center(
          child: Icon(Icons.inventory_2_outlined, size: 80, color: Colors.grey),
        ),
      );
    }

    return Column(
      children: [
        GestureDetector(
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => _FullScreenGallery(
                images: imageUrls,
                initialIndex: currentPage,
              ),
            ),
          ),
          child: Container(
            height: 250,
            decoration: BoxDecoration(
              color: Colors.grey[100],
              borderRadius: BorderRadius.circular(16),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: PageView.builder(
                itemCount: imageUrls.length,
                onPageChanged: onPageChanged,
                itemBuilder: (context, index) {
                  return CachedNetworkImage(
                    imageUrl: imageUrls[index],
                    fit: BoxFit.contain,
                    placeholder: (_, __) => const Center(
                      child: CircularProgressIndicator(),
                    ),
                    errorWidget: (_, __, ___) => const Center(
                      child: Icon(Icons.broken_image, size: 48, color: Colors.grey),
                    ),
                  );
                },
              ),
            ),
          ),
        ),
        if (imageUrls.length > 1) ...[
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(imageUrls.length, (index) {
              return Container(
                margin: const EdgeInsets.symmetric(horizontal: 3),
                width: currentPage == index ? 10 : 6,
                height: currentPage == index ? 10 : 6,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: currentPage == index
                      ? HelmTheme.primary
                      : Colors.grey[300],
                ),
              );
            }),
          ),
        ],
      ],
    );
  }
}

class _FullScreenGallery extends StatelessWidget {
  final List<String> images;
  final int initialIndex;

  const _FullScreenGallery({
    required this.images,
    required this.initialIndex,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text('${initialIndex + 1} / ${images.length}'),
      ),
      body: PhotoViewGallery.builder(
        scrollPhysics: const BouncingScrollPhysics(),
        pageController: PageController(initialPage: initialIndex),
        itemCount: images.length,
        builder: (context, index) {
          return PhotoViewGalleryPageOptions(
            imageProvider: NetworkImage(images[index]),
            minScale: PhotoViewComputedScale.contained,
            maxScale: PhotoViewComputedScale.covered * 3,
          );
        },
        loadingBuilder: (context, event) => const Center(
          child: CircularProgressIndicator(color: Colors.white),
        ),
      ),
    );
  }
}

class _CompatibilityBanner extends ConsumerWidget {
  final String productId;
  final String vesselId;
  final String vesselName;

  const _CompatibilityBanner({
    required this.productId,
    required this.vesselId,
    required this.vesselName,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final compat = ref.watch(
      compatibilityProvider((productId: productId, vesselId: vesselId)),
    );

    return compat.when(
      data: (result) {
        final isCompatible = result['compatible'] == true;
        return Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: isCompatible
                ? HelmTheme.success.withOpacity(0.1)
                : HelmTheme.accent.withOpacity(0.1),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: isCompatible
                  ? HelmTheme.success.withOpacity(0.3)
                  : HelmTheme.accent.withOpacity(0.3),
            ),
          ),
          child: Row(
            children: [
              Icon(
                isCompatible ? Icons.check_circle : Icons.warning,
                color: isCompatible ? HelmTheme.success : HelmTheme.accent,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  isCompatible
                      ? 'Compatible with $vesselName'
                      : 'Compatibility with $vesselName unconfirmed',
                  style: TextStyle(
                    fontWeight: FontWeight.w500,
                    color: isCompatible ? HelmTheme.success : HelmTheme.accent,
                  ),
                ),
              ),
            ],
          ),
        );
      },
      loading: () => const LinearProgressIndicator(),
      error: (_, __) => const SizedBox.shrink(),
    );
  }
}
