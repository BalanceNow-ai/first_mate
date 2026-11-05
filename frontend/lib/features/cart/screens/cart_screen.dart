import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/quantity_stepper.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/products/widgets/product_widgets.dart';

/// Review the cart: quantities, removal, per-line issues and the server's
/// subtotal, then continue to checkout.
class CartScreen extends ConsumerStatefulWidget {
  const CartScreen({super.key});

  @override
  ConsumerState<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends ConsumerState<CartScreen> {
  final Set<String> _busy = {};

  Future<void> _run(String lineId, Future<void> Function() action, String failure) async {
    setState(() => _busy.add(lineId));
    try {
      await action();
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: failure);
    } finally {
      if (mounted) setState(() => _busy.remove(lineId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = ref.watch(cartProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your cart'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh cart',
            onPressed: () => ref.invalidate(cartProvider),
          ),
        ],
      ),
      body: cart.when(
        data: (c) => c.isEmpty ? const _EmptyCart() : _CartBody(cart: c, busy: _busy, run: _run),
        loading: () => const LoadingView(message: 'Loading your cart'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load your cart',
          onRetry: () => ref.invalidate(cartProvider),
        ),
      ),
    );
  }
}

class _EmptyCart extends StatelessWidget {
  const _EmptyCart();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.shopping_cart_outlined, size: 72, color: HelmTheme.mutedText),
            const SizedBox(height: 16),
            Text('Your cart is empty', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: () => context.go('/products'),
              icon: const Icon(Icons.storefront),
              label: const Text('Browse parts'),
            ),
          ],
        ),
      ),
    );
  }
}

typedef _Runner = Future<void> Function(String lineId, Future<void> Function() action, String failure);

class _CartBody extends ConsumerWidget {
  const _CartBody({required this.cart, required this.busy, required this.run});

  final Cart cart;
  final Set<String> busy;
  final _Runner run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(cartProvider.notifier);
    final lines = [
      for (final line in cart.items)
        _CartLineTile(
          line: line,
          currency: cart.currency,
          busy: busy.contains(line.id),
          onQuantity: (q) => run(line.id, () => notifier.setQuantity(line.id, q), 'Could not update quantity'),
          onRemove: () => run(line.id, () => notifier.remove(line.id), 'Could not remove item'),
        ),
    ];
    final summary = _CartSummary(cart: cart);
    final wide = MediaQuery.sizeOf(context).width >= 900;
    if (wide) {
      return ContentWidth(
        maxWidth: 1100,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: 3, child: ListView(padding: const EdgeInsets.all(16), children: lines)),
            SizedBox(width: 340, child: Padding(padding: const EdgeInsets.all(16), child: summary)),
          ],
        ),
      );
    }
    return ContentWidth(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [...lines, const SizedBox(height: 8), summary],
      ),
    );
  }
}

class _CartLineTile extends StatelessWidget {
  const _CartLineTile({
    required this.line,
    required this.currency,
    required this.busy,
    required this.onQuantity,
    required this.onRemove,
  });

  final CartLine line;
  final String currency;
  final bool busy;
  final ValueChanged<int> onQuantity;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final p = line.product;
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 72,
                  height: 72,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: ProductImage(url: p.images.isEmpty ? null : p.images.first),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      InkWell(
                        onTap: () => context.go('/products/${line.productId}'),
                        child: Text(p.name,
                            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                      ),
                      if (p.brand != null) Text(p.brand!, style: theme.textTheme.bodySmall),
                      const SizedBox(height: 4),
                      PriceText(
                        effectiveCents: line.unitPriceCents,
                        regularCents: p.priceCents,
                        onSale: line.unitPriceCents < p.priceCents,
                        currency: currency,
                      ),
                      Text('each', style: theme.textTheme.bodySmall),
                    ],
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline),
                  tooltip: 'Remove ${p.name} from cart',
                  onPressed: busy ? null : onRemove,
                ),
              ],
            ),
            for (final issue in line.issues)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Semantics(
                  liveRegion: true,
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline, size: 18, color: HelmTheme.error),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(cartIssueText(issue, p),
                            style: const TextStyle(color: HelmTheme.error, fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 12,
              runSpacing: 8,
              children: [
                QuantityStepper(
                  value: line.quantity,
                  max: p.stockQuantity.clamp(1, 99),
                  enabled: !busy && p.isActive,
                  itemName: p.name,
                  onChanged: onQuantity,
                ),
                if (busy)
                  const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, semanticsLabel: 'Updating'),
                  ),
                Text(formatCents(line.lineTotalCents, currency: currency),
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CartSummary extends StatelessWidget {
  const _CartSummary({required this.cart});

  final Cart cart;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 12,
              children: [
                Text('Subtotal (${cart.itemCount} ${cart.itemCount == 1 ? 'item' : 'items'})'),
                Text(formatCents(cart.subtotalCents, currency: cart.currency),
                    style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 8),
            Text('Delivery and payment are confirmed at checkout.', style: theme.textTheme.bodySmall),
            if (cart.hasIssues) ...[
              const SizedBox(height: 12),
              const Text('Resolve the items marked above before checking out.',
                  style: TextStyle(color: HelmTheme.error)),
            ],
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: cart.hasIssues ? null : () => context.go('/checkout'),
              icon: const Icon(Icons.lock_outline),
              label: const Text('Proceed to checkout'),
            ),
          ],
        ),
      ),
    );
  }
}
