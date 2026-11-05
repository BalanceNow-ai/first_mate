import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';

/// Effective price, with the regular price struck through when on sale.
/// Both values are server-provided cents.
class PriceText extends StatelessWidget {
  const PriceText({
    super.key,
    required this.effectiveCents,
    required this.regularCents,
    required this.onSale,
    this.currency = 'NZD',
    this.large = false,
  });

  final int effectiveCents;
  final int regularCents;
  final bool onSale;
  final String currency;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final price = formatCents(effectiveCents, currency: currency);
    final regular = formatCents(regularCents, currency: currency);
    final style = (large ? theme.textTheme.headlineSmall : theme.textTheme.titleMedium)
        ?.copyWith(fontWeight: FontWeight.bold, color: onSale ? HelmTheme.error : HelmTheme.navy);
    return Semantics(
      label: onSale ? 'Sale price $price, was $regular' : 'Price $price',
      excludeSemantics: true,
      child: Wrap(
        crossAxisAlignment: WrapCrossAlignment.end,
        spacing: 8,
        children: [
          Text(price, style: style),
          if (onSale)
            Text(
              regular,
              style: theme.textTheme.bodyMedium?.copyWith(
                decoration: TextDecoration.lineThrough,
                color: HelmTheme.mutedText,
              ),
            ),
        ],
      ),
    );
  }
}

/// "In stock" / "Only N left" / "Out of stock".
class StockLabel extends StatelessWidget {
  const StockLabel({super.key, required this.inStock, required this.quantity});

  final bool inStock;
  final int quantity;

  @override
  Widget build(BuildContext context) {
    final (String text, Color color, IconData icon) = !inStock
        ? ('Out of stock', HelmTheme.error, Icons.remove_shopping_cart)
        : quantity <= 5
            ? ('Only $quantity left', HelmTheme.warning, Icons.inventory_2_outlined)
            : ('In stock', HelmTheme.success, Icons.check);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 4),
        Flexible(
          child: Text(text,
              style: TextStyle(color: HelmTheme.darken(color, 0.1), fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }
}

/// Product image with explicit loading, error and no-image states.
class ProductImage extends StatelessWidget {
  const ProductImage({super.key, required this.url, this.semanticLabel, this.fit = BoxFit.cover});

  final String? url;
  final String? semanticLabel;
  final BoxFit fit;

  Widget _placeholder({required IconData icon, String? text, Widget? overlay}) => ColoredBox(
        color: HelmTheme.surface,
        child: LayoutBuilder(builder: (context, constraints) {
          // Small thumbnails (e.g. cart lines) show the icon only.
          final roomy = constraints.maxHeight >= 96 && constraints.maxWidth >= 96;
          final size = constraints.maxHeight.isFinite ? (constraints.maxHeight * 0.45).clamp(16.0, 40.0) : 40.0;
          return Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                overlay ?? Icon(icon, size: size, color: HelmTheme.mutedText.withValues(alpha: 0.6)),
                if (text != null && roomy)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(text,
                        textAlign: TextAlign.center,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12, color: HelmTheme.mutedText)),
                  ),
              ],
            ),
          );
        }),
      );

  @override
  Widget build(BuildContext context) {
    if (url == null || url!.isEmpty) {
      return Semantics(
        label: semanticLabel == null ? 'No image' : '$semanticLabel, no image',
        image: true,
        excludeSemantics: true,
        child: _placeholder(icon: Icons.inventory_2_outlined),
      );
    }
    return Semantics(
      image: true,
      label: semanticLabel,
      child: Image.network(
        url!,
        fit: fit,
        semanticLabel: semanticLabel,
        loadingBuilder: (context, child, progress) {
          if (progress == null) return child;
          final total = progress.expectedTotalBytes;
          return _placeholder(
            icon: Icons.image_outlined,
            overlay: SizedBox(
              width: 28,
              height: 28,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                value: total == null ? null : progress.cumulativeBytesLoaded / total,
                semanticsLabel: 'Loading image',
              ),
            ),
          );
        },
        errorBuilder: (_, _, _) =>
            _placeholder(icon: Icons.broken_image_outlined, text: 'Image unavailable'),
      ),
    );
  }
}

/// Short vessel name for a fitment badge from the server's `nickname (…)` label.
String? vesselShortName(String? label) {
  if (label == null) return null;
  final i = label.indexOf(' (');
  return i > 0 ? label.substring(0, i) : label;
}

/// Fitment badge for a product, or a neutral hint when no vessel was checked.
class ProductFitment extends StatelessWidget {
  const ProductFitment({super.key, required this.fitment, this.vesselLabel, this.dense = true});

  final Fitment? fitment;
  final String? vesselLabel;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final f = fitment;
    if (f == null) {
      return Text('Fit not checked — choose a vessel',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText));
    }
    return FitmentBadge(fitment: f, vesselName: vesselShortName(vesselLabel), dense: dense);
  }
}

/// A product tile for the shop grid.
class ProductCard extends StatelessWidget {
  const ProductCard({super.key, required this.product, this.vesselLabel});

  final Product product;
  final String? vesselLabel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: () => context.go('/products/${product.id}'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: 130,
              child: ProductImage(url: product.primaryImage, semanticLabel: product.name),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (product.brand != null)
                      Text(product.brand!, style: theme.textTheme.labelMedium),
                    Semantics(
                      button: true,
                      child: Text(
                        product.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold),
                      ),
                    ),
                    const Spacer(),
                    if (product.fitment != null) ...[
                      ProductFitment(fitment: product.fitment, vesselLabel: vesselLabel),
                      const SizedBox(height: 6),
                    ],
                    PriceText(
                      effectiveCents: product.effectivePriceCents,
                      regularCents: product.priceCents,
                      onSale: product.onSale,
                      currency: product.currency,
                    ),
                    const SizedBox(height: 4),
                    StockLabel(inStock: product.inStock, quantity: product.stockQuantity),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A compact notice row (warning / info).
class NoticeBox extends StatelessWidget {
  const NoticeBox({
    super.key,
    required this.text,
    this.icon = Icons.info_outline,
    this.color = HelmTheme.primary,
    this.action,
  });

  final String text;
  final IconData icon;
  final Color color;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Icon(icon, color: HelmTheme.darken(color, 0.1)),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: action == null
                ? Text(text)
                : Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 8,
                    children: [Text(text), action!],
                  ),
          ),
        ],
      ),
    );
  }
}
