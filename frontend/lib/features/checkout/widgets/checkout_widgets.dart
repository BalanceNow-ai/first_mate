import 'dart:async';

import 'package:flutter/material.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';

/// "1 Delivery — 2 Review — 3 Payment".
class CheckoutStepHeader extends StatelessWidget {
  const CheckoutStepHeader({super.key, required this.step});

  final int step;

  static const labels = ['Delivery', 'Review', 'Payment'];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      label: 'Step ${step + 1} of 3: ${labels[step]}',
      excludeSemantics: true,
      child: Row(
        children: [
          for (var i = 0; i < labels.length; i++)
            Expanded(
              child: Row(children: [
                CircleAvatar(
                  radius: 14,
                  backgroundColor: i <= step ? HelmTheme.primary : theme.disabledColor,
                  child: Text('${i + 1}', style: const TextStyle(color: Colors.white, fontSize: 13)),
                ),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    labels[i],
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontWeight: i == step ? FontWeight.bold : FontWeight.normal),
                  ),
                ),
              ]),
            ),
        ],
      ),
    );
  }
}

/// One server delivery option; unavailable ones are disabled with the reason.
class DeliveryOptionTile extends StatelessWidget {
  const DeliveryOptionTile({super.key, required this.option, required this.selected, required this.onSelect});

  final DeliveryOption option;
  final bool selected;
  final VoidCallback onSelect;

  String get _title => switch (option.deliveryType) {
        DeliveryType.courier => option.serviceName ?? 'Courier',
        DeliveryType.helmDash => 'Helm Dash — delivered to your vessel',
        DeliveryType.clickAndCollect => 'Click & collect',
        _ => option.deliveryType,
      };

  String get _subtitle {
    if (!option.available) return 'Unavailable — ${option.reason ?? 'not offered right now'}';
    return switch (option.deliveryType) {
      DeliveryType.clickAndCollect =>
        'Free · collect from ${option.pickupLocation ?? 'the Helm store'}',
      DeliveryType.courier => [
          if (option.priceCents != null) 'From ${formatCents(option.priceCents!)} (exact price quoted for your address)',
          if (option.estimatedDays != null) 'about ${option.estimatedDays} business days',
          if (option.developmentRateCard) 'development rate card',
        ].join(' · '),
      DeliveryType.helmDash =>
        'Priced by distance to your vessel${option.operatingAreas.isEmpty ? '' : ' · ${option.operatingAreas.map((a) => a.name).join(', ')}'}',
      _ => '',
    };
  }

  IconData get _icon => switch (option.deliveryType) {
        DeliveryType.courier => Icons.local_shipping,
        DeliveryType.helmDash => Icons.sailing,
        _ => Icons.store,
      };

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: selected ? HelmTheme.primary : Colors.transparent, width: 2),
      ),
      // ListTile exposes one button node with enabled/selected state.
      child: ListTile(
        enabled: option.available,
        selected: selected,
        onTap: option.available ? onSelect : null,
        leading: Icon(
          selected ? Icons.radio_button_checked : (option.available ? Icons.radio_button_unchecked : Icons.block),
          color: selected ? HelmTheme.primary : null,
        ),
        title: Row(children: [
          Icon(_icon, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(_title)),
        ]),
        subtitle: Text(_subtitle),
      ),
    );
  }
}

/// A server quote: price, service, distance/ETA and its expiry.
class QuoteCard extends StatefulWidget {
  const QuoteCard({super.key, required this.quote, required this.onRequote, this.now = DateTime.now});

  final DeliveryQuote quote;
  final VoidCallback onRequote;
  final DateTime Function() now;

  @override
  State<QuoteCard> createState() => _QuoteCardState();
}

class _QuoteCardState extends State<QuoteCard> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final q = widget.quote;
    final now = widget.now();
    final left = q.expiresAt.difference(now);
    final expired = q.isExpired(now);
    final details = <String>[
      q.serviceName,
      if (q.nauticalMiles != null) '${q.nauticalMiles!.toStringAsFixed(2)} nm',
      if (q.estimatedMinutes != null) 'about ${q.estimatedMinutes} min once dispatched',
      if (q.estimatedDays != null) 'about ${q.estimatedDays} business days',
      if (q.operatingAreaName != null) q.operatingAreaName!,
    ];
    return Card(
      color: tintedCardColor(expired ? HelmTheme.warning : HelmTheme.success),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Semantics(
          liveRegion: true,
          container: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Expanded(
                  child: Text(
                    q.deliveryType == DeliveryType.helmDash ? 'Helm Dash quote' : 'Courier quote',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                Text(formatCents(q.priceCents), style: Theme.of(context).textTheme.titleMedium),
              ]),
              const SizedBox(height: 4),
              Text(details.join(' · ')),
              if (q.developmentRateCard)
                const Padding(
                  padding: EdgeInsets.only(top: 4),
                  child: LabelChip(label: 'Development rate card — local test pricing', color: HelmTheme.warning),
                ),
              if (q.freeShippingThresholdCents != null)
                Text('Free courier shipping on merchandise over ${formatCents(q.freeShippingThresholdCents!)}.'),
              const SizedBox(height: 4),
              if (expired)
                Row(children: [
                  const Expanded(child: Text('This quote has expired.', style: TextStyle(color: HelmTheme.error))),
                  TextButton(onPressed: widget.onRequote, child: const Text('Get a new quote')),
                ])
              else
                Text('Quote valid for ${left.inMinutes}:${(left.inSeconds % 60).toString().padLeft(2, '0')}',
                    style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
      ),
    );
  }
}

/// What to say (and offer) for a checkout / quote error from the server.
class CheckoutErrorCard extends StatelessWidget {
  const CheckoutErrorCard({
    super.key,
    required this.error,
    this.cart,
    this.onRequote,
    this.onBackToCart,
    this.onChangeDelivery,
    this.onRetry,
  });

  final Object error;
  final Cart? cart;
  final VoidCallback? onRequote;
  final VoidCallback? onBackToCart;
  final VoidCallback? onChangeDelivery;
  final VoidCallback? onRetry;

  String _names(List<String> ids) {
    final names = <String>[];
    for (final id in ids) {
      final line = cart?.items.where((l) => l.productId == id).firstOrNull;
      names.add(line?.product.name ?? 'a product');
    }
    return names.join(', ');
  }

  @override
  Widget build(BuildContext context) {
    final api = ApiError.from(error);
    String title = 'Checkout problem';
    String message = describeError(error);
    final actions = <Widget>[];
    if (api != null) {
      final ids = [for (final p in (api.extra['product_ids'] as List? ?? const [])) '$p'];
      switch (api.code) {
        case 'insufficient_stock':
          title = 'Not enough stock';
          message = ids.isEmpty
              ? api.detail
              : 'Not enough stock for: ${_names(ids)}. Reduce the quantity in your cart to continue.';
          if (onBackToCart != null) actions.add(FilledButton(onPressed: onBackToCart, child: const Text('Review cart')));
        case 'product_unavailable':
          title = 'Product unavailable';
          message = ids.isEmpty ? api.detail : 'No longer available: ${_names(ids)}. Remove it from your cart.';
          if (onBackToCart != null) actions.add(FilledButton(onPressed: onBackToCart, child: const Text('Review cart')));
        case 'cart_empty':
          title = 'Your cart is empty';
          if (onBackToCart != null) actions.add(FilledButton(onPressed: onBackToCart, child: const Text('Go to cart')));
        case 'dangerous_goods_restricted':
          title = 'Dangerous goods restriction';
          final products = [
            for (final p in (api.extra['products'] as List? ?? const []))
              if (p is Map && p['name'] is String) p['name'] as String,
          ];
          message = products.isEmpty ? api.detail : '${api.detail}\nRestricted: ${products.join(', ')}';
          if (onChangeDelivery != null) {
            actions.add(FilledButton(onPressed: onChangeDelivery, child: const Text('Choose another delivery method')));
          }
        case final code when requoteCodes.contains(code):
          title = code == 'quote_cart_changed' ? 'Your cart changed' : 'Delivery quote needs refreshing';
          if (onRequote != null) actions.add(FilledButton(onPressed: onRequote, child: const Text('Get a new quote')));
        case 'outside_operating_area':
          title = 'Outside the Helm Dash area';
        case 'courier_unavailable' || 'helm_dash_unavailable' || 'delivery_unavailable':
          title = 'Delivery method unavailable';
          if (onChangeDelivery != null) {
            actions.add(FilledButton(onPressed: onChangeDelivery, child: const Text('Choose another delivery method')));
          }
        case 'below_minimum_charge':
          title = 'Order total too low';
          final min = api.extra['min_charge_cents'];
          if (min is int) message = 'The order total must be at least ${formatCents(min)}. Add another item or remove the discount.';
        case 'payment_method_unavailable':
          title = 'Payment method unavailable';
        case 'entitlement_not_found' || 'entitlement_unavailable' || 'discount_exceeds_subtotal':
          title = 'Discount cannot be used';
        case ApiError.networkCode:
          title = 'Connection problem';
          message = 'Could not reach Helm. Your checkout attempt is kept — trying again is safe and will not '
              'create a second order.';
          if (onRetry != null) actions.add(FilledButton(onPressed: onRetry, child: const Text('Try again')));
        default:
          if (onRetry != null && (api.statusCode ?? 0) >= 500) {
            actions.add(FilledButton(onPressed: onRetry, child: const Text('Try again')));
          }
      }
    }
    return Semantics(
      liveRegion: true,
      container: true,
      child: Card(
        color: tintedCardColor(HelmTheme.error, 0.07),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                const Icon(Icons.error_outline, color: HelmTheme.error),
                const SizedBox(width: 8),
                Expanded(child: Text(title, style: Theme.of(context).textTheme.titleSmall)),
              ]),
              const SizedBox(height: 6),
              Text(message),
              if (api != null && api.code.isNotEmpty && api.code != ApiError.networkCode)
                Text('Code: ${api.code}', style: Theme.of(context).textTheme.bodySmall),
              if (actions.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: actions),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
