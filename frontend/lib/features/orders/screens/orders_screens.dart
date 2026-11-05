import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/checkout/payment/payment_panel.dart';
import 'package:helm_marine/features/orders/data/commerce_api.dart';
import 'package:helm_marine/features/orders/providers/orders_providers.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';

/// `GET /orders/` — the user's orders, newest first, paginated.
class OrdersScreen extends ConsumerStatefulWidget {
  const OrdersScreen({super.key});

  @override
  ConsumerState<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends ConsumerState<OrdersScreen> {
  int _page = 1;

  @override
  Widget build(BuildContext context) {
    final page = ref.watch(orderHistoryProvider(_page));
    return Scaffold(
      appBar: AppBar(title: const Text('My orders')),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(orderHistoryProvider(_page).future),
        child: ContentWidth(
          maxWidth: 820,
          child: page.when(
            loading: () => const LoadingView(message: 'Loading your orders…'),
            error: (e, _) => ErrorView(
              error: e,
              title: 'Could not load your orders',
              onRetry: () => ref.invalidate(orderHistoryProvider(_page)),
            ),
            data: (p) {
              if (p.items.isEmpty && p.page == 1) {
                return ListView(
                  padding: const EdgeInsets.all(24),
                  children: [
                    const Icon(Icons.receipt_long, size: 56, color: HelmTheme.mutedText),
                    const SizedBox(height: 12),
                    const Text('No orders yet', textAlign: TextAlign.center),
                    const SizedBox(height: 12),
                    Center(
                      child: FilledButton(
                        onPressed: () => context.go('/products'),
                        child: const Text('Shop parts'),
                      ),
                    ),
                  ],
                );
              }
              return ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text('${p.total} ${p.total == 1 ? 'order' : 'orders'}',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  for (final o in p.items)
                    OrderSummaryTile(order: o, onTap: () => context.go('/orders/${o.id}')),
                  if (p.pageCount > 1)
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        IconButton(
                          tooltip: 'Previous page',
                          onPressed: p.page > 1 ? () => setState(() => _page--) : null,
                          icon: const Icon(Icons.chevron_left),
                        ),
                        Text('Page ${p.page} of ${p.pageCount}'),
                        IconButton(
                          tooltip: 'Next page',
                          onPressed: p.hasNext ? () => setState(() => _page++) : null,
                          icon: const Icon(Icons.chevron_right),
                        ),
                      ],
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

/// A compact "recent orders" card for the profile page.
class RecentOrdersSection extends ConsumerWidget {
  const RecentOrdersSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final page = ref.watch(orderHistoryProvider(1));
    return page.when(
      loading: () => const Padding(padding: EdgeInsets.all(16), child: LoadingView()),
      error: (e, _) => Card(
        child: ListTile(
          leading: const Icon(Icons.error_outline, color: HelmTheme.error),
          title: const Text('Could not load your orders'),
          subtitle: Text(describeError(e)),
          trailing: TextButton(onPressed: () => ref.invalidate(orderHistoryProvider(1)), child: const Text('Retry')),
        ),
      ),
      data: (p) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (p.items.isEmpty)
            const Card(child: ListTile(leading: Icon(Icons.receipt_long), title: Text('No orders yet'))),
          for (final o in p.items.take(3))
            OrderSummaryTile(order: o, onTap: () => context.go('/orders/${o.id}')),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: () => context.go('/orders'),
              icon: const Icon(Icons.receipt_long),
              label: const Text('All orders'),
            ),
          ),
        ],
      ),
    );
  }
}

/// One order with its amounts, delivery, payment and tracking.
class OrderDetailScreen extends ConsumerStatefulWidget {
  const OrderDetailScreen({super.key, required this.orderId});

  final String orderId;

  @override
  ConsumerState<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends ConsumerState<OrderDetailScreen> {
  bool _cancelling = false;

  Future<void> _cancel() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Cancel this order?'),
        content: const Text(
            'The reserved stock is released and the items go back to your cart. Any discount you used is restored.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep order')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: HelmTheme.error),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Cancel order'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _cancelling = true);
    try {
      await ref.read(commerceApiProvider).cancelOrder(widget.orderId);
      ref.invalidate(cartProvider);
      ref.invalidate(orderHistoryProvider);
      ref.invalidate(orderDetailProvider(widget.orderId));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Order cancelled — the items are back in your cart.')));
      }
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not cancel');
      ref.invalidate(orderDetailProvider(widget.orderId));
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(orderDetailProvider(widget.orderId));
    return Scaffold(
      appBar: AppBar(
        title: Text(async.value == null ? 'Order' : 'Order ${async.value!.orderNumber}'),
        leading: IconButton(
          tooltip: 'All orders',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.canPop() ? context.pop() : context.go('/orders'),
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(orderDetailProvider(widget.orderId)),
          ),
        ],
      ),
      body: async.when(
        loading: () => const LoadingView(message: 'Loading order…'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load this order',
          onRetry: () => ref.invalidate(orderDetailProvider(widget.orderId)),
        ),
        data: (order) => RefreshIndicator(
          onRefresh: () => ref.refresh(orderDetailProvider(widget.orderId).future),
          child: ContentWidth(
            maxWidth: 820,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                StatusChips(order: order),
                const SizedBox(height: 8),
                Text('Placed ${formatLocalDateTime(order.createdAt)}'),
                if (order.paidAt != null) Text('Paid ${formatLocalDateTime(order.paidAt!)}'),
                if (order.cancelledAt != null)
                  Text('Cancelled ${formatLocalDateTime(order.cancelledAt!)}'
                      '${order.cancelReason != null ? ' (${order.cancelReason!.replaceAll('_', ' ')})' : ''}'),
                if (order.isPendingPayment) ...[
                  const SizedBox(height: 12),
                  _AwaitingPayment(order: order, cancelling: _cancelling, onCancel: _cancel),
                ],
                _Section(title: 'Items', child: OrderItemsList(items: order.items)),
                _Section(title: 'Amounts', child: OrderAmounts(order: order)),
                _Section(title: 'Delivery', child: OrderDeliveryDetails(order: order)),
                if (order.isHelmDash && order.isPaid) _HelmDashLink(orderId: order.id),
                if (order.delivery.deliveryType == DeliveryType.courier)
                  _Section(title: 'Tracking', child: _CourierTracking(order: order)),
                _Section(
                  title: 'Payment',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(paymentStatusLabel(order.paymentStatus)),
                      if (order.paymentProvider == 'local')
                        const Text('Paid through the local TEST MODE provider — no real charge.'),
                      if (order.refundedCents > 0)
                        Text('Refunds: ${formatCents(order.refundedCents)} returned to your card.'),
                    ],
                  ),
                ),
                if (order.notes != null) _Section(title: 'Notes', child: Text(order.notes!)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AwaitingPayment extends StatelessWidget {
  const _AwaitingPayment({required this.order, required this.cancelling, required this.onCancel});

  final Order order;
  final bool cancelling;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: HelmTheme.warning.withValues(alpha: 0.08),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Awaiting payment', style: Theme.of(context).textTheme.titleMedium),
            if (order.expiresAt != null) ...[
              const SizedBox(height: 8),
              ReservationCountdown(expiresAt: order.expiresAt!),
            ],
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (order.canRetryPayment)
                FilledButton.icon(
                  onPressed: () => context.go('/orders/${order.id}/pay'),
                  icon: const Icon(Icons.payment),
                  label: Text(order.paymentStatus == 'failed' ? 'Retry payment' : 'Pay now'),
                ),
              if (order.canCancel)
                OutlinedButton.icon(
                  onPressed: cancelling ? null : onCancel,
                  icon: const Icon(Icons.cancel_outlined),
                  style: OutlinedButton.styleFrom(foregroundColor: HelmTheme.error),
                  label: const Text('Cancel order'),
                ),
            ]),
            if (order.canCancel)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('Cancelling returns the items to your cart.', style: Theme.of(context).textTheme.bodySmall),
              ),
          ],
        ),
      ),
    );
  }
}

class _HelmDashLink extends ConsumerWidget {
  const _HelmDashLink({required this.orderId});

  final String orderId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final delivery = ref.watch(orderDeliveryProvider(orderId));
    return _Section(
      title: 'Helm Dash delivery',
      child: delivery.when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text(describeError(e)),
        data: (d) => d == null
            ? const Text('Your Helm Dash delivery is being set up.')
            : Row(
                children: [
                  Expanded(child: Text(d.statusLabel)),
                  FilledButton.icon(
                    onPressed: () => context.go('/dash/${d.id}'),
                    icon: const Icon(Icons.sailing),
                    label: const Text('Track delivery'),
                  ),
                ],
              ),
      ),
    );
  }
}

class _CourierTracking extends StatelessWidget {
  const _CourierTracking({required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    final t = order.tracking;
    if (!t.hasAny) return const Text('Tracking details appear here once your order is dispatched.');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (t.isTest)
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: LabelChip(label: 'TEST LABEL — not a real courier booking', color: HelmTheme.warning),
          ),
        if (t.courier != null) Text('Courier: ${t.courier}'),
        if (t.trackingNumber != null) SelectableText('Tracking number: ${t.trackingNumber}'),
        if (t.shipmentStatus != null) Text('Shipment: ${t.shipmentStatus!.replaceAll('_', ' ')}'),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Semantics(header: true, child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
              const SizedBox(height: 8),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

/// `/orders/:orderId/pay` — retry or complete payment for an existing order.
class OrderPaymentScreen extends StatelessWidget {
  const OrderPaymentScreen({super.key, required this.orderId});

  final String orderId;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Payment')),
      body: ContentWidth(
        maxWidth: 720,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [PaymentPanel(orderId: orderId)],
        ),
      ),
    );
  }
}
