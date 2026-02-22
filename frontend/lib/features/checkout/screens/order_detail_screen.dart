import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

final orderDetailProvider =
    FutureProvider.family<Map<String, dynamic>, String>((ref, orderId) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getOrder(orderId);
});

class OrderDetailScreen extends ConsumerWidget {
  final String orderId;

  const OrderDetailScreen({super.key, required this.orderId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final orderState = ref.watch(orderDetailProvider(orderId));

    return Scaffold(
      appBar: AppBar(title: const Text('Order Details')),
      body: orderState.when(
        data: (order) {
          final orderStatus = order['status'] as String? ?? 'pending';
          final subtotal =
              (order['subtotal'] as num?)?.toDouble() ?? 0;
          final shipping =
              (order['shipping_cost'] as num?)?.toDouble() ?? 0;
          final total = (order['total'] as num?)?.toDouble() ?? 0;
          final deliveryType = order['delivery_type'] as String? ?? 'courier';
          final trackingNumber = order['tracking_number'] as String?;
          final courier = order['courier'] as String?;
          final items = (order['items'] as List?)
                  ?.cast<Map<String, dynamic>>() ??
              [];
          final createdAt = order['created_at'] as String? ?? '';
          final shortId =
              (order['id'] as String?)?.substring(0, 8).toUpperCase() ?? '';

          return RefreshIndicator(
            onRefresh: () async =>
                ref.invalidate(orderDetailProvider(orderId)),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Order header
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'Order #$shortId',
                              style: Theme.of(context)
                                  .textTheme
                                  .titleMedium
                                  ?.copyWith(fontWeight: FontWeight.bold),
                            ),
                            _StatusChip(status: orderStatus),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          createdAt.isNotEmpty
                              ? 'Placed ${_formatDate(createdAt)}'
                              : '',
                          style: TextStyle(
                              color: Colors.grey[600], fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Items
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Items',
                            style: Theme.of(context)
                                .textTheme
                                .titleSmall
                                ?.copyWith(fontWeight: FontWeight.bold)),
                        const Divider(),
                        ...items.map((item) {
                          final qty = item['quantity'] as int? ?? 1;
                          final unitPrice =
                              (item['unit_price'] as num?)?.toDouble() ?? 0;
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    'Product (x$qty)',
                                    style: const TextStyle(fontSize: 14),
                                  ),
                                ),
                                Text(
                                  '\$${(unitPrice * qty).toStringAsFixed(2)}',
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w500),
                                ),
                              ],
                            ),
                          );
                        }),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Totals
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        _TotalRow(label: 'Subtotal', value: subtotal),
                        _TotalRow(label: 'Shipping', value: shipping),
                        const Divider(),
                        _TotalRow(
                          label: 'Total',
                          value: total,
                          isBold: true,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Delivery info
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Delivery',
                            style: Theme.of(context)
                                .textTheme
                                .titleSmall
                                ?.copyWith(fontWeight: FontWeight.bold)),
                        const Divider(),
                        Row(
                          children: [
                            Icon(_deliveryIcon(deliveryType),
                                size: 18, color: Colors.grey[600]),
                            const SizedBox(width: 8),
                            Text(_deliveryLabel(deliveryType)),
                          ],
                        ),
                        if (trackingNumber != null) ...[
                          const SizedBox(height: 8),
                          Row(
                            children: [
                              Icon(Icons.qr_code,
                                  size: 18, color: Colors.grey[600]),
                              const SizedBox(width: 8),
                              Text('Tracking: $trackingNumber'),
                            ],
                          ),
                        ],
                        if (courier != null) ...[
                          const SizedBox(height: 4),
                          Row(
                            children: [
                              Icon(Icons.local_shipping,
                                  size: 18, color: Colors.grey[600]),
                              const SizedBox(width: 8),
                              Text('Courier: $courier'),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline,
                  size: 48, color: HelmTheme.error),
              const SizedBox(height: 16),
              Text('Failed to load order\n$error',
                  textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () =>
                    ref.invalidate(orderDetailProvider(orderId)),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDate(String isoDate) {
    try {
      final dt = DateTime.parse(isoDate);
      return '${dt.day}/${dt.month}/${dt.year}';
    } catch (_) {
      return isoDate;
    }
  }

  IconData _deliveryIcon(String type) {
    switch (type) {
      case 'helm_dash':
        return Icons.directions_boat;
      case 'click_and_collect':
        return Icons.store;
      default:
        return Icons.local_shipping;
    }
  }

  String _deliveryLabel(String type) {
    switch (type) {
      case 'helm_dash':
        return 'Helm Dash Maritime Delivery';
      case 'click_and_collect':
        return 'Click & Collect — Westhaven Marina';
      default:
        return 'Standard Shipping';
    }
  }
}

class _StatusChip extends StatelessWidget {
  final String status;

  const _StatusChip({required this.status});

  Color get _color {
    switch (status) {
      case 'paid':
      case 'fulfilled':
        return HelmTheme.success;
      case 'shipped':
        return HelmTheme.accent;
      case 'delivered':
        return HelmTheme.success;
      case 'cancelled':
        return HelmTheme.error;
      default:
        return HelmTheme.primary;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: _color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _color.withOpacity(0.3)),
      ),
      child: Text(
        status.toUpperCase(),
        style: TextStyle(
          color: _color,
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _TotalRow extends StatelessWidget {
  final String label;
  final double value;
  final bool isBold;

  const _TotalRow({
    required this.label,
    required this.value,
    this.isBold = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label,
              style: TextStyle(
                fontWeight: isBold ? FontWeight.bold : FontWeight.normal,
                fontSize: isBold ? 16 : 14,
              )),
          Text(
            '\$${value.toStringAsFixed(2)}',
            style: TextStyle(
              fontWeight: isBold ? FontWeight.bold : FontWeight.w500,
              fontSize: isBold ? 16 : 14,
              color: isBold ? HelmTheme.primary : null,
            ),
          ),
        ],
      ),
    );
  }
}
