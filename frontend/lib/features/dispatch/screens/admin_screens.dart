import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/dispatch/data/dispatch_api.dart';
import 'package:helm_marine/features/dispatch/screens/dispatcher_screens.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_common.dart';

final allOperatorsProvider = FutureProvider.autoDispose<List<OperatorProfile>>((ref) {
  return ref.watch(staffApiProvider).operators();
});

final payoutsProvider = FutureProvider.autoDispose<List<Payout>>((ref) {
  return ref.watch(staffApiProvider).payouts();
});

final reconciliationProvider = FutureProvider.autoDispose.family<Reconciliation, String?>((ref, period) {
  return ref.watch(staffApiProvider).reconciliation(period: period);
});

const rateUnconfiguredExplanation =
    'No operator share is configured (decision D10), so payout records are created as "rate unconfigured" with '
    'no amount and cannot be approved. Live payouts are disabled; approving only records a decision.';

/// `/staff/admin` — operating areas, operator profiles, payouts, reconciliation.
class HelmDashAdminScreen extends StatelessWidget {
  const HelmDashAdminScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'admin'},
      title: 'Helm Dash admin',
      builder: (context, me) => DefaultTabController(
        length: 4,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Helm Dash admin'),
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(text: 'Areas'),
              Tab(text: 'Operators'),
              Tab(text: 'Payouts'),
              Tab(text: 'Reconciliation'),
            ]),
          ),
          body: const TabBarView(children: [_AreasTab(), _OperatorsTab(), _PayoutsTab(), _ReconciliationTab()]),
        ),
      ),
    );
  }
}

class _AreasTab extends ConsumerWidget {
  const _AreasTab();

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final id = TextEditingController();
    final name = TextEditingController();
    final lat = TextEditingController();
    final lng = TextEditingController();
    final radius = TextEditingController();
    var enabled = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New operating area'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: id, decoration: const InputDecoration(labelText: 'Id (lowercase, e.g. bay-of-islands)')),
              TextField(controller: name, decoration: const InputDecoration(labelText: 'Name')),
              TextField(controller: lat, decoration: const InputDecoration(labelText: 'Centre latitude')),
              TextField(controller: lng, decoration: const InputDecoration(labelText: 'Centre longitude')),
              TextField(controller: radius, decoration: const InputDecoration(labelText: 'Radius (nautical miles)')),
              SwitchListTile(
                title: const Text('Enabled'),
                value: enabled,
                onChanged: (v) => setState(() => enabled = v),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Back')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok == true && context.mounted) {
      final la = double.tryParse(lat.text.trim());
      final lo = double.tryParse(lng.text.trim());
      final r = double.tryParse(radius.text.trim());
      if (la == null || lo == null || r == null) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Enter numeric coordinates and radius.')));
      } else {
        final created = await runStaffAction(
          context,
          () => ref.read(staffApiProvider).createArea(
              id: id.text.trim(), name: name.text.trim(), centerLat: la, centerLng: lo, radiusNm: r, enabled: enabled),
          success: 'Area created',
        );
        if (created != null) ref.invalidate(dispatchAreasProvider);
      }
    }
    for (final c in [id, name, lat, lng, radius]) {
      c.dispose();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final areas = ref.watch(dispatchAreasProvider);
    return ContentWidth(
      maxWidth: 900,
      child: areas.when(
        loading: () => const LoadingView(),
        error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(dispatchAreasProvider)),
        data: (list) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                onPressed: () => _create(context, ref),
                icon: const Icon(Icons.add),
                label: const Text('New area'),
              ),
            ),
            for (final a in list)
              Card(
                child: SwitchListTile(
                  title: Text(a.name),
                  subtitle: Text('${a.id} · centre ${a.centerLat}, ${a.centerLng} · radius ${a.radiusNm} nm'),
                  value: a.enabled,
                  onChanged: (v) async {
                    final r = await runStaffAction(
                      context,
                      () => ref.read(staffApiProvider).updateArea(a.id, {'enabled': v}),
                      success: v ? 'Area enabled' : 'Area disabled',
                    );
                    if (r != null) ref.invalidate(dispatchAreasProvider);
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _OperatorsTab extends ConsumerWidget {
  const _OperatorsTab();

  Future<void> _create(BuildContext context, WidgetRef ref, List<OperatingArea> areas) async {
    final userId = TextEditingController();
    final name = TextEditingController();
    final vessel = TextEditingController();
    final cert = TextEditingController();
    String? areaId = areas.isEmpty ? null : areas.first.id;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('New operator profile'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Text('The user must already hold the operator role (grant-role). The profile starts inactive.'),
              TextField(controller: userId, decoration: const InputDecoration(labelText: 'User id (UUID)')),
              TextField(controller: name, decoration: const InputDecoration(labelText: 'Display name')),
              TextField(controller: vessel, decoration: const InputDecoration(labelText: 'Vessel name (optional)')),
              DropdownButtonFormField<String>(
                initialValue: areaId,
                decoration: const InputDecoration(labelText: 'Area'),
                items: [for (final a in areas) DropdownMenuItem(value: a.id, child: Text(a.name))],
                onChanged: (v) => setState(() => areaId = v),
              ),
              TextField(
                controller: cert,
                decoration: const InputDecoration(
                  labelText: 'Certification reference (optional)',
                  helperText: 'Recorded as unverified — Helm does not certify operators.',
                ),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Back')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok == true && context.mounted && areaId != null) {
      final created = await runStaffAction(
        context,
        () => ref.read(staffApiProvider).createOperator(
              userId: userId.text.trim(),
              displayName: name.text.trim(),
              areaId: areaId!,
              vesselName: vessel.text.trim(),
              certificationReference: cert.text.trim(),
            ),
        success: 'Operator profile created (inactive)',
      );
      if (created != null) ref.invalidate(allOperatorsProvider);
    }
    for (final c in [userId, name, vessel, cert]) {
      c.dispose();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ops = ref.watch(allOperatorsProvider);
    final areas = ref.watch(dispatchAreasProvider).value ?? const <OperatingArea>[];
    return ContentWidth(
      maxWidth: 900,
      child: ops.when(
        loading: () => const LoadingView(),
        error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(allOperatorsProvider)),
        data: (list) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                onPressed: () => _create(context, ref, areas),
                icon: const Icon(Icons.person_add),
                label: const Text('New operator profile'),
              ),
            ),
            if (list.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No operator profiles yet.')),
            for (final o in list)
              Card(
                child: ListTile(
                  title: Text('${o.displayName}${o.vesselName == null ? '' : ' · ${o.vesselName}'}'),
                  subtitle: Text('${o.userId}\narea ${o.areaId} · ${o.active ? 'active' : 'inactive'} · '
                      '${o.isOnline ? 'online' : 'offline'}'
                      '${o.certificationReference == null ? '' : ' · cert ref (unverified): ${o.certificationReference}'}'),
                  isThreeLine: true,
                  trailing: TextButton(
                    onPressed: () async {
                      final r = await runStaffAction(
                        context,
                        () => ref.read(staffApiProvider).setOperatorActive(o.userId, !o.active),
                        success: o.active ? 'Operator deactivated' : 'Operator activated',
                      );
                      if (r != null) ref.invalidate(allOperatorsProvider);
                    },
                    child: Text(o.active ? 'Deactivate' : 'Activate'),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _PayoutsTab extends ConsumerWidget {
  const _PayoutsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final payouts = ref.watch(payoutsProvider);
    return ContentWidth(
      maxWidth: 900,
      child: payouts.when(
        loading: () => const LoadingView(),
        error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(payoutsProvider)),
        data: (list) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (list.any((p) => p.status == 'rate_unconfigured'))
              const Card(
                child: ListTile(leading: Icon(Icons.info_outline, color: HelmTheme.warning), title: Text(rateUnconfiguredExplanation)),
              ),
            if (list.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No payout records.')),
            for (final p in list)
              Card(
                child: ListTile(
                  title: Text('Delivery ${p.deliveryId}'),
                  subtitle: Text('Operator ${p.operatorId}\nGross fee ${formatCents(p.grossFeeCents)} · '
                      '${p.amountCents == null ? 'no amount (share unset)' : 'payout ${formatCents(p.amountCents!)}'} · '
                      '${p.status.replaceAll('_', ' ')} · ${formatLocalDateTime(p.createdAt)}'),
                  isThreeLine: true,
                  trailing: p.status == 'pending_review'
                      ? TextButton(
                          onPressed: () async {
                            final r = await runStaffAction(context, () => ref.read(staffApiProvider).approvePayout(p.id),
                                success: 'Approval recorded (no payment is made)');
                            if (r != null) ref.invalidate(payoutsProvider);
                          },
                          child: const Text('Approve'),
                        )
                      : null,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ReconciliationTab extends ConsumerStatefulWidget {
  const _ReconciliationTab();

  @override
  ConsumerState<_ReconciliationTab> createState() => _ReconciliationTabState();
}

class _ReconciliationTabState extends ConsumerState<_ReconciliationTab> {
  String? _period;
  final _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final rec = ref.watch(reconciliationProvider(_period));
    return ContentWidth(
      maxWidth: 900,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            SizedBox(
              width: 200,
              child: TextField(
                controller: _input,
                decoration: const InputDecoration(labelText: 'Period (YYYY-MM)'),
                onSubmitted: (v) => setState(() => _period = v.trim().isEmpty ? null : v.trim()),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton(
              onPressed: () => setState(() => _period = _input.text.trim().isEmpty ? null : _input.text.trim()),
              child: const Text('Show'),
            ),
          ]),
          const SizedBox(height: 12),
          rec.when(
            loading: () => const LoadingView(),
            error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(reconciliationProvider(_period))),
            data: (r) => Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Period ${r.period} (${r.currency})', style: Theme.of(context).textTheme.titleMedium),
                  AmountRow(label: 'Deliveries completed', value: '${r.deliveredCount}'),
                  AmountRow(label: 'Delivery fees collected', value: formatCents(r.deliveryFeesCents)),
                  AmountRow(
                    label: 'Operator share',
                    value: r.operatorShareBps == null ? 'not configured' : '${r.operatorShareBps! / 100}%',
                  ),
                  AmountRow(label: 'Live payouts', value: r.livePayoutsEnabled ? 'enabled' : 'disabled'),
                  const Divider(),
                  for (final s in r.payoutsByStatus)
                    AmountRow(
                      label: '${s.status.replaceAll('_', ' ')} (${s.count})',
                      value: '${formatCents(s.amountCents)} of ${formatCents(s.grossFeeCents)} gross',
                    ),
                  if (r.operatorShareBps == null) ...[
                    const SizedBox(height: 8),
                    const Text(rateUnconfiguredExplanation),
                  ],
                ]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
