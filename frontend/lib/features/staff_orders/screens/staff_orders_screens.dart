import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/dispatch/data/dispatch_api.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_common.dart';

final staffOrdersProvider = FutureProvider.autoDispose.family<OrderPage, StaffOrderFilter>((ref, filter) {
  return ref.watch(staffApiProvider).staffOrders(filter);
});

final staffOrderProvider = FutureProvider.autoDispose.family<Order, String>((ref, id) {
  return ref.watch(staffApiProvider).staffOrder(id);
});

const _orderStatuses = [
  'pending_payment', 'paid', 'ready_for_dispatch', 'dispatched', 'delivered', 'collected', 'cancelled', 'expired',
  'refunded', 'payment_review',
];
const _paymentStatuses = ['unpaid', 'requires_action', 'processing', 'failed', 'succeeded', 'partially_refunded', 'refunded'];

/// Fulfilment targets the server's state machine allows from [order]'s status
/// (mirrors `FULFILMENT_TRANSITIONS`; the server remains authoritative).
List<String> fulfilmentTargets(Order order) {
  final type = order.delivery.deliveryType ?? DeliveryType.courier;
  return switch ((order.status, type)) {
    ('paid', DeliveryType.clickAndCollect) => ['ready_for_dispatch', 'collected'],
    ('paid', DeliveryType.helmDash) => ['ready_for_dispatch', 'dispatched'],
    ('paid', _) => ['ready_for_dispatch'],
    ('ready_for_dispatch', DeliveryType.clickAndCollect) => ['collected'],
    ('ready_for_dispatch', _) => ['dispatched'],
    ('dispatched', DeliveryType.courier || DeliveryType.helmDash) => ['delivered'],
    _ => const [],
  };
}

/// `/staff/orders` — `GET /orders/admin/all` with filters.
class StaffOrdersScreen extends ConsumerStatefulWidget {
  const StaffOrdersScreen({super.key});

  @override
  ConsumerState<StaffOrdersScreen> createState() => _StaffOrdersScreenState();
}

class _StaffOrdersScreenState extends ConsumerState<StaffOrdersScreen> {
  StaffOrderFilter _filter = const StaffOrderFilter();
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Widget _dropdown(String label, String? value, List<String> values, ValueChanged<String?> onChanged,
      {String Function(String)? text}) {
    return SizedBox(
      width: 220,
      child: DropdownButtonFormField<String?>(
        initialValue: value,
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: [
          const DropdownMenuItem<String?>(value: null, child: Text('Any')),
          for (final v in values) DropdownMenuItem<String?>(value: v, child: Text(text?.call(v) ?? v)),
        ],
        onChanged: onChanged,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'dispatcher'},
      title: 'Staff orders',
      builder: (context, me) {
        final page = ref.watch(staffOrdersProvider(_filter));
        return Scaffold(
          appBar: AppBar(
            title: const Text('Staff orders'),
            actions: [
              IconButton(
                tooltip: 'Refresh',
                icon: const Icon(Icons.refresh),
                onPressed: () => ref.invalidate(staffOrdersProvider(_filter)),
              ),
            ],
          ),
          body: ContentWidth(
            maxWidth: 1100,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.end, children: [
                  _dropdown('Order status', _filter.status, _orderStatuses,
                      (v) => setState(() => _filter = _filter.copyWith(status: () => v, page: 1)),
                      text: orderStatusLabel),
                  _dropdown('Payment', _filter.paymentStatus, _paymentStatuses,
                      (v) => setState(() => _filter = _filter.copyWith(paymentStatus: () => v, page: 1)),
                      text: paymentStatusLabel),
                  _dropdown('Delivery', _filter.deliveryType,
                      const [DeliveryType.courier, DeliveryType.helmDash, DeliveryType.clickAndCollect],
                      (v) => setState(() => _filter = _filter.copyWith(deliveryType: () => v, page: 1)),
                      text: DeliveryType.label),
                  SizedBox(
                    width: 220,
                    child: TextField(
                      controller: _search,
                      decoration: const InputDecoration(labelText: 'Order number starts with', prefixIcon: Icon(Icons.search)),
                      onSubmitted: (v) => setState(
                          () => _filter = _filter.copyWith(orderNumber: () => v.trim().isEmpty ? null : v.trim(), page: 1)),
                    ),
                  ),
                ]),
                const SizedBox(height: 12),
                ...page.when(
                  loading: () => [const LoadingView(message: 'Loading orders…')],
                  error: (e, _) => [ErrorView(error: e, onRetry: () => ref.invalidate(staffOrdersProvider(_filter)))],
                  data: (p) => [
                    Text('${p.total} orders', style: Theme.of(context).textTheme.bodySmall),
                    if (p.items.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No orders match.')),
                    for (final o in p.items)
                      OrderSummaryTile(order: o, showCustomer: true, onTap: () => context.go('/staff/orders/${o.id}')),
                    if (p.pageCount > 1)
                      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                        IconButton(
                          tooltip: 'Previous page',
                          onPressed: p.page > 1 ? () => setState(() => _filter = _filter.copyWith(page: p.page - 1)) : null,
                          icon: const Icon(Icons.chevron_left),
                        ),
                        Text('Page ${p.page} of ${p.pageCount}'),
                        IconButton(
                          tooltip: 'Next page',
                          onPressed: p.hasNext ? () => setState(() => _filter = _filter.copyWith(page: p.page + 1)) : null,
                          icon: const Icon(Icons.chevron_right),
                        ),
                      ]),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// `/staff/orders/:id` — staff order detail and actions.
class StaffOrderDetailScreen extends ConsumerWidget {
  const StaffOrderDetailScreen({super.key, required this.orderId});

  final String orderId;

  Future<void> _fulfil(BuildContext context, WidgetRef ref, Order order, String target) async {
    String? tracking;
    String? courier;
    if (target == 'dispatched' && order.delivery.deliveryType == DeliveryType.courier) {
      final t = TextEditingController(text: order.tracking.trackingNumber ?? '');
      final c = TextEditingController(text: order.tracking.courier ?? '');
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Mark dispatched'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: t, decoration: const InputDecoration(labelText: 'Tracking number (optional)')),
            TextField(controller: c, decoration: const InputDecoration(labelText: 'Courier (optional)')),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Back')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Mark dispatched')),
          ],
        ),
      );
      tracking = t.text.trim();
      courier = c.text.trim();
      t.dispose();
      c.dispose();
      if (ok != true) return;
    } else if (!context.mounted ||
        !await confirmAction(context,
            title: 'Mark ${orderStatusLabel(target).toLowerCase()}?',
            message: 'Order ${order.orderNumber} moves from "${orderStatusLabel(order.status)}" to '
                '"${orderStatusLabel(target)}". The customer is notified.',
            action: 'Confirm')) {
      return;
    }
    if (!context.mounted) return;
    final updated = await runStaffAction(
      context,
      () => ref.read(staffApiProvider).updateFulfilment(order.id, target, trackingNumber: tracking, courier: courier),
      success: 'Order updated: ${orderStatusLabel(target)}',
    );
    if (updated != null) ref.invalidate(staffOrderProvider(orderId));
  }

  Future<void> _label(BuildContext context, WidgetRef ref, Order order) async {
    final shipment = await runStaffAction(context, () => ref.read(staffApiProvider).createShipment(order.id));
    if (shipment == null || !context.mounted) return;
    ref.invalidate(staffOrderProvider(orderId));
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(shipment.isTest ? 'TEST courier label created' : 'Courier label created'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (shipment.isTest)
            const Text('This is a local test booking — no real courier was booked.',
                style: TextStyle(color: HelmTheme.warning, fontWeight: FontWeight.bold)),
          Text('Provider: ${shipment.provider}'),
          if (shipment.serviceName != null) Text('Service: ${shipment.serviceName}'),
          if (shipment.labelReference != null) SelectableText('Label: ${shipment.labelReference}'),
          if (shipment.trackingNumber != null) SelectableText('Tracking: ${shipment.trackingNumber}'),
          Text('Status: ${shipment.status}'),
        ]),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
      ),
    );
  }

  Future<void> _refund(BuildContext context, WidgetRef ref, Order order) async {
    final refundable = order.totalCents - order.refundedCents;
    final result = await showDialog<(int, String)>(
      context: context,
      builder: (context) => _RefundDialog(order: order, refundableCents: refundable),
    );
    if (result == null || !context.mounted) return;
    final (cents, reason) = result;
    final confirmed = await confirmAction(
      context,
      title: 'Refund ${formatCents(cents)}?',
      message: 'Refund ${formatCents(cents)} of order ${order.orderNumber} to the customer\'s card. '
          'This cannot be undone.',
      action: 'Refund ${formatCents(cents)}',
    );
    if (!confirmed || !context.mounted) return;
    // One key per submitted refund; every retry of this submission reuses it,
    // so a lost response can never refund twice.
    final key = newRefundIdempotencyKey();
    RefundResult? refund;
    while (true) {
      if (!context.mounted) return;
      refund = await runStaffAction(
        context,
        () => ref.read(staffApiProvider).refund(order.id, amountCents: cents, reason: reason, idempotencyKey: key),
      );
      if (refund != null) break;
      if (!context.mounted) return;
      final retry = await confirmAction(
        context,
        title: 'Refund not confirmed',
        message: 'The refund request did not complete. Retrying sends the same request again and can never '
            'refund twice.',
        action: 'Retry refund',
      );
      if (!retry) break;
    }
    if (refund == null || !context.mounted) return;
    ref.invalidate(staffOrderProvider(orderId));
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(refundResultText(refund))));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RoleGate(
      roles: const {'dispatcher'},
      title: 'Staff order',
      builder: (context, me) {
        final async = ref.watch(staffOrderProvider(orderId));
        return Scaffold(
          appBar: AppBar(
            title: Text(async.value == null ? 'Order' : 'Order ${async.value!.orderNumber}'),
            actions: [
              IconButton(
                tooltip: 'Refresh',
                icon: const Icon(Icons.refresh),
                onPressed: () => ref.invalidate(staffOrderProvider(orderId)),
              ),
            ],
          ),
          body: async.when(
            loading: () => const LoadingView(),
            error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(staffOrderProvider(orderId))),
            data: (order) {
              final targets = fulfilmentTargets(order);
              return ContentWidth(
                maxWidth: 960,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    StatusChips(order: order),
                    const SizedBox(height: 8),
                    Text('Customer ${order.userId ?? '-'}'),
                    Text('Placed ${formatLocalDateTime(order.createdAt)}'),
                    if (order.reviewReason != null)
                      Text('Needs review: ${order.reviewReason}', style: const TextStyle(color: HelmTheme.warning)),
                    StaffSection(
                      title: 'Fulfilment',
                      child: targets.isEmpty
                          ? Text('No fulfilment step available from "${orderStatusLabel(order.status)}".')
                          : Wrap(spacing: 8, runSpacing: 8, children: [
                              for (final t in targets)
                                FilledButton(
                                  onPressed: () => _fulfil(context, ref, order, t),
                                  child: Text('Mark ${orderStatusLabel(t).toLowerCase()}'),
                                ),
                            ]),
                    ),
                    if (order.delivery.deliveryType == DeliveryType.courier)
                      StaffSection(
                        title: 'Courier',
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          if (order.tracking.isTest)
                            const LabelChip(label: 'TEST LABEL — not a real courier booking', color: HelmTheme.warning),
                          if (order.tracking.trackingNumber != null) Text('Tracking ${order.tracking.trackingNumber}'),
                          if (order.tracking.shipmentStatus != null) Text('Shipment ${order.tracking.shipmentStatus}'),
                          const SizedBox(height: 8),
                          OutlinedButton.icon(
                            onPressed: order.isPaid && !order.isUnderPaymentReview ? () => _label(context, ref, order) : null,
                            icon: const Icon(Icons.local_shipping),
                            label: const Text('Create courier label (test booking in development)'),
                          ),
                        ]),
                      ),
                    if (me.role == 'admin')
                      StaffSection(
                        title: 'Refund',
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('Refunded so far ${formatCents(order.refundedCents)} of ${formatCents(order.totalCents)}.'),
                          const SizedBox(height: 8),
                          OutlinedButton.icon(
                            onPressed: order.isRefundable
                                ? () => _refund(context, ref, order)
                                : null,
                            icon: const Icon(Icons.undo),
                            style: OutlinedButton.styleFrom(foregroundColor: HelmTheme.error),
                            label: const Text('Refund…'),
                          ),
                        ]),
                      ),
                    StaffSection(title: 'Items', child: OrderItemsList(items: order.items)),
                    StaffSection(title: 'Amounts', child: OrderAmounts(order: order)),
                    StaffSection(title: 'Delivery', child: OrderDeliveryDetails(order: order)),
                    if (order.notes != null) StaffSection(title: 'Customer notes', child: Text(order.notes!)),
                  ],
                ),
              );
            },
          ),
        );
      },
    );
  }
}

/// A fresh refund Idempotency-Key (8-100 chars of `A-Z a-z 0-9 _ - : .`).
String newRefundIdempotencyKey([Random? random]) {
  final r = random ?? Random.secure();
  return 'refund-${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${r.nextInt(0x7fffffff).toRadixString(36)}${r.nextInt(0x7fffffff).toRadixString(36)}';
}

/// What a refund response means for the admin.
String refundResultText(RefundResult r) {
  final test = r.testMode ? ' (TEST MODE — no real money moved)' : '';
  if (r.status == 'duplicate_request') {
    return 'This refund was already requested — nothing was refunded again. '
        'Refunded so far ${formatCents(r.refundedCents)}.$test';
  }
  return 'Refund ${r.status}: ${formatCents(r.amountCents)}$test. Refunded so far ${formatCents(r.refundedCents)}.';
}

/// Parses "12.34" / "12" dollars into integer cents without floating point.
int? parseDollarsToCents(String input) {
  final m = RegExp(r'^\s*(\d{1,7})(?:\.(\d{1,2}))?\s*$').firstMatch(input);
  if (m == null) return null;
  final dollars = int.parse(m.group(1)!);
  final frac = (m.group(2) ?? '').padRight(2, '0');
  return dollars * 100 + int.parse(frac);
}

class _RefundDialog extends StatefulWidget {
  const _RefundDialog({required this.order, required this.refundableCents});

  final Order order;
  final int refundableCents;

  @override
  State<_RefundDialog> createState() => _RefundDialogState();
}

class _RefundDialogState extends State<_RefundDialog> {
  final _amount = TextEditingController();
  final _reason = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _amount.dispose();
    _reason.dispose();
    super.dispose();
  }

  void _submit() {
    final cents = parseDollarsToCents(_amount.text);
    if (cents == null || cents < 1) {
      setState(() => _error = 'Enter an amount such as 12.50');
      return;
    }
    if (cents > widget.refundableCents) {
      setState(() => _error = 'At most ${formatCents(widget.refundableCents)} can be refunded');
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Give a reason (at least 3 characters)');
      return;
    }
    Navigator.pop(context, (cents, _reason.text.trim()));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Refund order ${widget.order.orderNumber}'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        Text('Up to ${formatCents(widget.refundableCents)} can be refunded.'),
        TextField(
          controller: _amount,
          decoration: const InputDecoration(labelText: 'Amount (NZD)', prefixText: r'$'),
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
        ),
        TextField(controller: _reason, maxLength: 500, decoration: const InputDecoration(labelText: 'Reason *')),
        if (_error != null) Text(_error!, style: const TextStyle(color: HelmTheme.error)),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Back')),
        FilledButton(onPressed: _submit, child: const Text('Continue')),
      ],
    );
  }
}
