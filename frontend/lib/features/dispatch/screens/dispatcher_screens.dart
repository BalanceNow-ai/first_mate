import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/dispatch/data/dispatch_api.dart';
import 'package:helm_marine/features/dispatch/widgets/dispatch_widgets.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_common.dart';

final dispatchDeliveriesProvider = FutureProvider.autoDispose.family<List<DispatchDelivery>, DeliveryFilter>((ref, f) {
  return ref.watch(staffApiProvider).deliveries(f);
});

final dispatchDeliveryProvider = FutureProvider.autoDispose.family<DispatchDelivery, String>((ref, id) {
  return ref.watch(staffApiProvider).delivery(id);
});

final dispatchAreasProvider = FutureProvider.autoDispose<List<OperatingArea>>((ref) {
  return ref.watch(staffApiProvider).areas();
});

/// Active operators serving an area.
final areaOperatorsProvider = FutureProvider.autoDispose.family<List<OperatorProfile>, String?>((ref, areaId) {
  return ref.watch(staffApiProvider).operators(areaId: areaId, active: true);
});

const deliveryStatuses = [
  'awaiting_dispatch', 'assigned', 'accepted', 'picked_up', 'en_route', 'delivered', 'failed', 'cancelled',
];

/// `/staff/dispatch` — the dispatcher console.
class DispatchConsoleScreen extends ConsumerStatefulWidget {
  const DispatchConsoleScreen({super.key});

  @override
  ConsumerState<DispatchConsoleScreen> createState() => _DispatchConsoleScreenState();
}

class _DispatchConsoleScreenState extends ConsumerState<DispatchConsoleScreen> {
  DeliveryFilter _filter = const DeliveryFilter();

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'dispatcher'},
      title: 'Dispatch console',
      builder: (context, me) {
        final list = ref.watch(dispatchDeliveriesProvider(_filter));
        final areas = ref.watch(dispatchAreasProvider).value ?? const <OperatingArea>[];
        return Scaffold(
          appBar: AppBar(
            title: const Text('Dispatch console'),
            actions: [
              IconButton(
                tooltip: 'Refresh',
                icon: const Icon(Icons.refresh),
                onPressed: () => ref.invalidate(dispatchDeliveriesProvider(_filter)),
              ),
            ],
          ),
          body: ContentWidth(
            maxWidth: 1100,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  SizedBox(
                    width: 220,
                    child: DropdownButtonFormField<String?>(
                      initialValue: _filter.status,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: 'Status'),
                      items: [
                        const DropdownMenuItem<String?>(value: null, child: Text('Any')),
                        for (final s in deliveryStatuses)
                          DropdownMenuItem<String?>(value: s, child: Text(deliveryStatusLabel(s))),
                      ],
                      onChanged: (v) => setState(
                          () => _filter = DeliveryFilter(status: v, areaId: _filter.areaId, activeOnly: _filter.activeOnly)),
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: DropdownButtonFormField<String?>(
                      initialValue: _filter.areaId,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: 'Area'),
                      items: [
                        const DropdownMenuItem<String?>(value: null, child: Text('All areas')),
                        for (final a in areas) DropdownMenuItem<String?>(value: a.id, child: Text(a.name)),
                      ],
                      onChanged: (v) => setState(
                          () => _filter = DeliveryFilter(status: _filter.status, areaId: v, activeOnly: _filter.activeOnly)),
                    ),
                  ),
                  FilterChip(
                    label: const Text('Active only'),
                    selected: _filter.activeOnly,
                    onSelected: (v) => setState(
                        () => _filter = DeliveryFilter(status: _filter.status, areaId: _filter.areaId, activeOnly: v)),
                  ),
                ]),
                const SizedBox(height: 12),
                ...list.when(
                  loading: () => [const LoadingView(message: 'Loading deliveries…')],
                  error: (e, _) => [ErrorView(error: e, onRetry: () => ref.invalidate(dispatchDeliveriesProvider(_filter)))],
                  data: (items) => [
                    Text('${items.length} deliveries', style: Theme.of(context).textTheme.bodySmall),
                    if (items.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No deliveries match.')),
                    for (final d in items) DeliveryTile(delivery: d, onTap: () => context.go('/staff/dispatch/${d.id}')),
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

/// `/staff/dispatch/:id` — events, latest location, assignment, cancel / fail.
class DispatchDeliveryScreen extends ConsumerStatefulWidget {
  const DispatchDeliveryScreen({super.key, required this.deliveryId});

  final String deliveryId;

  @override
  ConsumerState<DispatchDeliveryScreen> createState() => _DispatchDeliveryScreenState();
}

class _DispatchDeliveryScreenState extends ConsumerState<DispatchDeliveryScreen> {
  String? _operatorId;
  final _note = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  void _reload() {
    ref.invalidate(dispatchDeliveryProvider(widget.deliveryId));
    ref.invalidate(dispatchDeliveriesProvider);
  }

  Future<void> _run(Future<Object?> Function() action, String success) async {
    setState(() => _busy = true);
    final result = await runStaffAction(context, action, success: success);
    if (mounted) setState(() => _busy = false);
    if (result != null) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'dispatcher'},
      title: 'Delivery',
      builder: (context, me) {
        final async = ref.watch(dispatchDeliveryProvider(widget.deliveryId));
        return Scaffold(
          appBar: AppBar(
            title: Text(async.value?.orderNumber == null ? 'Delivery' : 'Delivery · ${async.value!.orderNumber}'),
            actions: [IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: _reload)],
          ),
          body: async.when(
            loading: () => const LoadingView(),
            error: (e, _) => ErrorView(error: e, onRetry: _reload),
            data: (d) {
              final canAssign = const {'awaiting_dispatch', 'assigned', 'accepted'}.contains(d.status);
              final canCancel = const {'awaiting_dispatch', 'assigned', 'accepted'}.contains(d.status);
              final canFail = const {'accepted', 'picked_up', 'en_route'}.contains(d.status);
              final api = ref.read(staffApiProvider);
              return ContentWidth(
                maxWidth: 1000,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Row(children: [
                      DeliveryStatusChip(status: d.status),
                      const SizedBox(width: 12),
                      Expanded(child: Text(d.operatorName == null ? 'Unassigned' : 'Skipper ${d.operatorName}')),
                      TextButton(
                        onPressed: () => context.go('/staff/orders/${d.orderId}'),
                        child: const Text('Open order'),
                      ),
                    ]),
                    const SizedBox(height: 12),
                    DeliveryMap(delivery: d),
                    StaffSection(title: 'Latest location', child: LatestLocationText(location: d.latestLocation)),
                    StaffSection(
                      title: 'Job',
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(d.deliveryLocationName ?? 'Pinned position'),
                        Text('${d.deliveryPoint.lat.toStringAsFixed(5)}, ${d.deliveryPoint.lng.toStringAsFixed(5)}'),
                        Text('Area ${d.areaId ?? '-'} · ${d.nauticalMiles?.toStringAsFixed(2) ?? '?'} nm · '
                            'fee ${formatCents(d.deliveryFeeCents)}'),
                        if (d.estimatedDeliveryMinutes != null) Text('Estimated ${d.estimatedDeliveryMinutes} min'),
                        Text('Created ${formatLocalDateTime(d.createdAt)}'),
                      ]),
                    ),
                    if (canAssign)
                      StaffSection(
                        title: d.operatorId == null ? 'Assign a skipper' : 'Reassign',
                        child: Consumer(builder: (context, ref, _) {
                          final ops = ref.watch(areaOperatorsProvider(d.areaId));
                          return ops.when(
                            loading: () => const LinearProgressIndicator(),
                            error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(areaOperatorsProvider(d.areaId))),
                            data: (list) {
                              if (list.isEmpty) {
                                return const Text('No active operators serve this area. An admin can create and activate one.');
                              }
                              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                                DropdownButtonFormField<String>(
                                  initialValue: _operatorId,
                                  isExpanded: true,
                                  decoration: const InputDecoration(labelText: 'Operator'),
                                  items: [
                                    for (final o in list)
                                      DropdownMenuItem(
                                        value: o.userId,
                                        child: Text('${o.displayName}${o.vesselName == null ? '' : ' · ${o.vesselName}'}'
                                            ' — ${o.isOnline ? 'online' : 'offline'}'),
                                      ),
                                  ],
                                  onChanged: (v) => setState(() => _operatorId = v),
                                ),
                                TextField(controller: _note, decoration: const InputDecoration(labelText: 'Note (optional)')),
                                const SizedBox(height: 8),
                                Align(
                                  alignment: Alignment.centerLeft,
                                  child: FilledButton.icon(
                                    onPressed: _busy || _operatorId == null
                                        ? null
                                        : () => _run(
                                              () => api.assign(d.id, _operatorId!, note: _note.text.trim()),
                                              'Delivery assigned',
                                            ),
                                    icon: const Icon(Icons.person_add),
                                    label: const Text('Assign'),
                                  ),
                                ),
                              ]);
                            },
                          );
                        }),
                      ),
                    if (canCancel || canFail)
                      StaffSection(
                        title: 'Exceptions',
                        child: Wrap(spacing: 8, runSpacing: 8, children: [
                          if (canCancel)
                            OutlinedButton(
                              onPressed: _busy
                                  ? null
                                  : () async {
                                      final reason = await askReason(context, title: 'Cancel this delivery?', action: 'Cancel delivery');
                                      if (reason != null) await _run(() => api.cancelDelivery(d.id, reason: reason), 'Delivery cancelled');
                                    },
                              child: const Text('Cancel delivery'),
                            ),
                          if (canFail)
                            OutlinedButton(
                              onPressed: _busy
                                  ? null
                                  : () async {
                                      final reason = await askReason(context, title: 'Mark delivery failed?', action: 'Mark failed');
                                      if (reason != null) await _run(() => api.failDelivery(d.id, reason: reason), 'Delivery marked failed');
                                    },
                              child: const Text('Mark failed'),
                            ),
                        ]),
                      ),
                    StaffSection(title: 'Events', child: DeliveryEvents(events: d.events ?? const [])),
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
