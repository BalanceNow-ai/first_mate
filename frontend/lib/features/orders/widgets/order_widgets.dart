import 'package:flutter/material.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:intl/intl.dart';

final _dateFormat = DateFormat('d MMM yyyy, h:mm a');

String formatLocalDateTime(DateTime t) => _dateFormat.format(t.toLocal());

/// An opaque tint for status cards (a translucent Card colour lets the
/// elevation shadow show through and looks muddy).
Color tintedCardColor(Color color, [double strength = 0.08]) =>
    Color.alphaBlend(color.withValues(alpha: strength), Colors.white);

Color orderStatusColor(String status) => switch (status) {
      'paid' || 'ready_for_dispatch' || 'dispatched' => HelmTheme.ocean,
      'delivered' || 'collected' => HelmTheme.success,
      'pending_payment' || 'payment_review' => HelmTheme.warning,
      'cancelled' || 'expired' || 'refunded' => HelmTheme.mutedText,
      _ => HelmTheme.mutedText,
    };

Color paymentStatusColor(String status) => switch (status) {
      'succeeded' => HelmTheme.success,
      'failed' => HelmTheme.error,
      'requires_action' || 'processing' => HelmTheme.warning,
      'partially_refunded' || 'refunded' => HelmTheme.ocean,
      _ => HelmTheme.mutedText,
    };

class LabelChip extends StatelessWidget {
  const LabelChip({super.key, required this.label, required this.color, this.icon, this.semanticPrefix});

  final String label;
  final Color color;
  final IconData? icon;
  final String? semanticPrefix;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticPrefix == null ? label : '$semanticPrefix: $label',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: color.withValues(alpha: 0.5)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 16, color: color), const SizedBox(width: 4)],
            Flexible(child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600))),
          ],
        ),
      ),
    );
  }
}

/// Order and payment status labels.
class StatusChips extends StatelessWidget {
  const StatusChips({super.key, required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        LabelChip(
          label: orderStatusLabel(order.status),
          color: orderStatusColor(order.status),
          semanticPrefix: 'Order status',
        ),
        LabelChip(
          label: paymentStatusLabel(order.paymentStatus),
          color: paymentStatusColor(order.paymentStatus),
          icon: Icons.credit_card,
          semanticPrefix: 'Payment',
        ),
      ],
    );
  }
}

/// A "label ...... value" row for amounts.
class AmountRow extends StatelessWidget {
  const AmountRow({super.key, required this.label, required this.value, this.bold = false, this.color});

  final String label;
  final String value;
  final bool bold;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final style = bold
        ? Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold, color: color)
        : Theme.of(context).textTheme.bodyMedium?.copyWith(color: color);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(child: Text(label, style: style)),
          Text(value, style: style),
        ],
      ),
    );
  }
}

/// Server-computed amounts of an order.
class OrderAmounts extends StatelessWidget {
  const OrderAmounts({super.key, required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        AmountRow(label: 'Subtotal', value: formatCents(order.subtotalCents)),
        if (order.discountCents > 0)
          AmountRow(label: 'Crew Rewards discount', value: '-${formatCents(order.discountCents)}', color: HelmTheme.success),
        AmountRow(
          label: order.delivery.freeShippingApplied ? 'Shipping (free shipping applied)' : 'Shipping',
          value: formatCents(order.shippingCents),
        ),
        const Divider(),
        AmountRow(label: 'Total (${order.currency})', value: formatCents(order.totalCents), bold: true),
        if (order.refundedCents > 0)
          AmountRow(label: 'Refunded', value: '-${formatCents(order.refundedCents)}', color: HelmTheme.ocean),
      ],
    );
  }
}

/// Order lines.
class OrderItemsList extends StatelessWidget {
  const OrderItemsList({super.key, required this.items});

  final List<OrderItem> items;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (final i in items)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(i.productName),
            subtitle: Text(
              '${i.sku} · ${i.quantity} × ${formatCents(i.unitPriceCents)}'
              '${i.listPriceCents > i.unitPriceCents ? ' (was ${formatCents(i.listPriceCents)})' : ''}',
            ),
            trailing: Text(formatCents(i.lineTotalCents), style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
      ],
    );
  }
}

/// Where and how the order is delivered.
class OrderDeliveryDetails extends StatelessWidget {
  const OrderDeliveryDetails({super.key, required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    final d = order.delivery;
    final lines = <String>[];
    switch (d.deliveryType) {
      case DeliveryType.courier:
        final a = d.shippingAddress ?? const {};
        lines.addAll([
          for (final k in ['name', 'line1', 'line2', 'suburb'])
            if ((a[k] as String?)?.isNotEmpty ?? false) a[k] as String,
          [a['city'], a['postcode']].whereType<String>().join(' '),
          if (a['phone'] is String) 'Phone ${a['phone']}',
        ]);
        if (d.serviceName != null) {
          lines.add('${d.serviceName}${d.estimatedDays != null ? ' · about ${d.estimatedDays} business days' : ''}');
        }
      case DeliveryType.helmDash:
        final h = d.helmDash ?? const {};
        final lat = (h['lat'] as num?)?.toDouble();
        final lng = (h['lng'] as num?)?.toDouble();
        lines.addAll([
          if (h['location_name'] is String) h['location_name'] as String,
          if (lat != null && lng != null) '${lat.toStringAsFixed(5)}, ${lng.toStringAsFixed(5)}',
          if (h['vessel_name'] is String) 'Vessel: ${h['vessel_name']}',
          if (h['phone'] is String) 'Phone ${h['phone']}',
          if (h['note'] is String) 'Note: ${h['note']}',
          if (h['nautical_miles'] is num) '${(h['nautical_miles'] as num).toStringAsFixed(2)} nm from the warehouse',
          if (d.estimatedMinutes != null) 'Estimated ${d.estimatedMinutes} min once dispatched',
        ]);
      case DeliveryType.clickAndCollect:
        lines.add('Collect from ${d.pickupLocation ?? 'the Helm store'}');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(DeliveryType.label(d.deliveryType), style: const TextStyle(fontWeight: FontWeight.w600)),
        for (final l in lines) Text(l),
      ],
    );
  }
}

/// A row in an order list.
class OrderSummaryTile extends StatelessWidget {
  const OrderSummaryTile({super.key, required this.order, required this.onTap, this.showCustomer = false});

  final OrderSummary order;
  final VoidCallback onTap;
  final bool showCustomer;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        onTap: onTap,
        leading: Icon(switch (order.deliveryType) {
          'helm_dash' => Icons.sailing,
          'click_and_collect' => Icons.store,
          _ => Icons.local_shipping,
        }),
        title: Text('Order ${order.orderNumber}', style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${formatLocalDateTime(order.createdAt)} · ${order.itemCount} '
                '${order.itemCount == 1 ? 'item' : 'items'} · ${DeliveryType.label(order.deliveryType)}'),
            if (showCustomer && order.userId != null) Text('Customer ${order.userId}'),
            if (order.reviewReason != null) Text('Review: ${order.reviewReason}'),
            const SizedBox(height: 4),
            Wrap(spacing: 6, runSpacing: 6, children: [
              LabelChip(
                label: orderStatusLabel(order.status),
                color: orderStatusColor(order.status),
                semanticPrefix: 'Order status',
              ),
              LabelChip(
                label: paymentStatusLabel(order.paymentStatus),
                color: paymentStatusColor(order.paymentStatus),
                semanticPrefix: 'Payment',
              ),
            ]),
          ],
        ),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(formatCents(order.totalCents), style: const TextStyle(fontWeight: FontWeight.bold)),
            if (order.refundedCents > 0) Text('-${formatCents(order.refundedCents)} refunded'),
          ],
        ),
      ),
    );
  }
}
