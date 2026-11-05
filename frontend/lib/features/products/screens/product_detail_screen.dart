import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:helm_marine/core/models/catalogue.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/widgets/quantity_stepper.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/products/widgets/product_widgets.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class ProductDetailScreen extends ConsumerWidget {
  const ProductDetailScreen({super.key, required this.productId});

  final String productId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final product = ref.watch(productDetailProvider(productId));
    return Scaffold(
      appBar: AppBar(title: Text(product.value?.name ?? 'Product')),
      body: product.when(
        data: (p) => _ProductDetails(product: p),
        loading: () => const LoadingView(message: 'Loading product'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load this product',
          onRetry: () => ref.invalidate(productDetailProvider(productId)),
        ),
      ),
    );
  }
}

class _ProductDetails extends ConsumerWidget {
  const _ProductDetails({required this.product});

  final Product product;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final vessel = ref.watch(shoppingVesselProvider);
    final dgTypes = ref.watch(publicConfigProvider).value?.delivery.dangerousGoodsDeliveryTypes ?? const [];
    final wide = MediaQuery.sizeOf(context).width >= 900;

    final gallery = _Gallery(product: product);

    final info = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (product.brand != null) Text(product.brand!, style: theme.textTheme.titleSmall),
        Text(product.name, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text('SKU ${product.sku}', style: theme.textTheme.bodySmall),
        const SizedBox(height: 12),
        PriceText(
          effectiveCents: product.effectivePriceCents,
          regularCents: product.priceCents,
          onSale: product.onSale,
          currency: product.currency,
          large: true,
        ),
        const SizedBox(height: 8),
        Semantics(
          container: true,
          child: StockLabel(inStock: product.inStock, quantity: product.stockQuantity),
        ),
        const SizedBox(height: 16),
        if (product.fitment != null)
          Semantics(
            container: true,
            child: _FitmentPanel(fitment: product.fitment!, vesselName: vessel?.nickname),
          )
        else if (vessel == null)
          const Text('Add a vessel to check whether this part fits your boat.')
        else
          const Text('Fit not checked — choose a vessel in the shop to check fitment.'),
        if (product.dangerousGoods) ...[
          const SizedBox(height: 12),
          Semantics(
            container: true,
            child: _Notice(
              icon: Icons.warning_amber,
              text: dgTypes.isEmpty
                  ? 'Dangerous goods — delivery options are restricted.'
                  : 'Dangerous goods — available by '
                        '${dgTypes.map((t) => t.replaceAll('_', ' ')).join(', ')} only.',
            ),
          ),
        ],
        const SizedBox(height: 16),
        _AddToCart(product: product),
      ],
    );

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ContentWidth(
          maxWidth: 1100,
          child: wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: gallery),
                    const SizedBox(width: 24),
                    Expanded(child: info),
                  ],
                )
              : Column(children: [gallery, const SizedBox(height: 16), info]),
        ),
        const SizedBox(height: 24),
        ContentWidth(
          maxWidth: 1100,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (product.description != null) ...[
                Semantics(header: true, child: Text('Description', style: theme.textTheme.titleMedium)),
                const SizedBox(height: 8),
                Text(product.description!),
                const SizedBox(height: 16),
              ],
              if (product.oemPartNumbers.isNotEmpty) ...[
                Semantics(header: true, child: Text('OEM part numbers', style: theme.textTheme.titleMedium)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final n in product.oemPartNumbers)
                      Chip(label: Text(n, semanticsLabel: 'OEM part number $n')),
                  ],
                ),
                const SizedBox(height: 16),
              ],
              _CompatibilitySection(productId: product.id),
              const SizedBox(height: 16),
              if (product.specifications != null && product.specifications!.isNotEmpty) ...[
                Semantics(header: true, child: Text('Specifications', style: theme.textTheme.titleMedium)),
                const SizedBox(height: 8),
                for (final e in product.specifications!.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 160,
                          child: Text(
                            e.key.replaceAll('_', ' '),
                            style: const TextStyle(color: HelmTheme.mutedText),
                          ),
                        ),
                        Expanded(child: Text('${e.value}')),
                      ],
                    ),
                  ),
              ],
              if (product.weightGrams != null) ...[
                const SizedBox(height: 8),
                Text('Shipping weight: ${product.weightGrams} g', style: theme.textTheme.bodySmall),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _FitmentPanel extends StatelessWidget {
  const _FitmentPanel({required this.fitment, this.vesselName});

  final Fitment fitment;
  final String? vesselName;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FitmentBadge(fitment: fitment, vesselName: vesselName),
        const SizedBox(height: 6),
        Text(fitment.message),
        for (final r in fitment.reasons)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text('• $r', style: Theme.of(context).textTheme.bodySmall),
          ),
      ],
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: HelmTheme.warning.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(icon, color: HelmTheme.warning),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _AddToCart extends ConsumerStatefulWidget {
  const _AddToCart({required this.product});

  final Product product;

  @override
  ConsumerState<_AddToCart> createState() => _AddToCartState();
}

class _AddToCartState extends ConsumerState<_AddToCart> {
  int _quantity = 1;
  bool _adding = false;

  int get _max => widget.product.stockQuantity.clamp(1, 99);

  Future<void> _add() async {
    setState(() => _adding = true);
    try {
      await ref.read(cartProvider.notifier).add(widget.product.id, quantity: _quantity);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Added $_quantity × ${widget.product.name} to your cart'),
          action: SnackBarAction(label: 'View cart', onPressed: () => context.go('/cart')),
        ),
      );
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not add to cart');
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final available = widget.product.inStock;
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        QuantityStepper(
          value: _quantity,
          max: _max,
          enabled: available && !_adding,
          onChanged: (q) => setState(() => _quantity = q),
        ),
        ElevatedButton.icon(
          onPressed: available && !_adding ? _add : null,
          icon: const Icon(Icons.add_shopping_cart),
          label: Text(available ? 'Add to cart' : 'Out of stock'),
        ),
      ],
    );
  }
}

/// Product images with previous/next controls and a position label.
class _Gallery extends StatefulWidget {
  const _Gallery({required this.product});

  final Product product;

  @override
  State<_Gallery> createState() => _GalleryState();
}

class _GalleryState extends State<_Gallery> {
  final _controller = PageController();
  int _index = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _go(int i) =>
      _controller.animateToPage(i, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final images = p.images;
    if (images.length <= 1) {
      return AspectRatio(
        aspectRatio: 4 / 3,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: ProductImage(url: p.primaryImage, semanticLabel: p.name, fit: BoxFit.contain),
        ),
      );
    }
    return Column(
      children: [
        AspectRatio(
          aspectRatio: 4 / 3,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: PageView(
              controller: _controller,
              onPageChanged: (i) => setState(() => _index = i),
              children: [
                for (final (i, url) in images.indexed)
                  InteractiveViewer(
                    child: ProductImage(
                      url: url,
                      semanticLabel: '${p.name}, image ${i + 1} of ${images.length}',
                      fit: BoxFit.contain,
                    ),
                  ),
              ],
            ),
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              icon: const Icon(Icons.chevron_left),
              tooltip: 'Previous image',
              onPressed: _index > 0 ? () => _go(_index - 1) : null,
            ),
            Text('${_index + 1} / ${images.length}'),
            IconButton(
              icon: const Icon(Icons.chevron_right),
              tooltip: 'Next image',
              onPressed: _index < images.length - 1 ? () => _go(_index + 1) : null,
            ),
          ],
        ),
      ],
    );
  }
}

/// The public "known to fit" list (verified rules only).
class _CompatibilitySection extends ConsumerWidget {
  const _CompatibilitySection({required this.productId});

  final String productId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final compat = ref.watch(productCompatibilityProvider(productId));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(header: true, child: Text('Known to fit', style: theme.textTheme.titleMedium)),
        const SizedBox(height: 8),
        compat.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(8),
            child: LinearProgressIndicator(semanticsLabel: 'Loading compatibility'),
          ),
          error: (e, _) => Row(
            children: [
              Expanded(child: Text('Could not load compatibility: ${describeError(e)}')),
              TextButton(
                onPressed: () => ref.invalidate(productCompatibilityProvider(productId)),
                child: const Text('Retry'),
              ),
            ],
          ),
          data: (c) => _KnownToFitList(compatibility: c),
        ),
      ],
    );
  }
}

class _KnownToFitList extends StatelessWidget {
  const _KnownToFitList({required this.compatibility});

  final ProductCompatibility compatibility;

  @override
  Widget build(BuildContext context) {
    final c = compatibility;
    if (c.universal) {
      return const Text('Universal part — suitable for any vessel.');
    }
    if (c.knownToFit.isEmpty) {
      return const Text('No verified fitment recorded yet. Check the OEM part number before buying.');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final k in c.knownToFit)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.verified, color: HelmTheme.success),
            title: Text(k.description),
            subtitle: Text(
              [
                k.fitmentType.replaceAll('_', ' '),
                'confidence ${(k.confidenceScore * 100).round()}%',
                if (k.isSynthetic) 'synthetic test data',
              ].join(' · '),
            ),
          ),
      ],
    );
  }
}
