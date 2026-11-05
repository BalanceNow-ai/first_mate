import 'package:flutter/material.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

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

/// Product image with a neutral placeholder.
class ProductImage extends StatelessWidget {
  const ProductImage({super.key, required this.url, this.semanticLabel, this.fit = BoxFit.cover});

  final String? url;
  final String? semanticLabel;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    final placeholder = ColoredBox(
      color: HelmTheme.surface,
      child: Center(
        child: Icon(Icons.inventory_2_outlined, size: 40, color: HelmTheme.mutedText.withValues(alpha: 0.6)),
      ),
    );
    if (url == null || url!.isEmpty) return placeholder;
    return Semantics(
      image: true,
      label: semanticLabel,
      child: Image.network(
        url!,
        fit: fit,
        loadingBuilder: (context, child, progress) => progress == null ? child : placeholder,
        errorBuilder: (_, _, _) => placeholder,
      ),
    );
  }
}
