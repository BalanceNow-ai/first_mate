import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/contractors/providers/contractor_providers.dart';

/// Account-menu entries: "Service jobs" for everyone, "Contractor inbox" for
/// members of a contractor organization (`GET /contractors/me`).
class ServiceMenuEntries extends ConsumerWidget {
  const ServiceMenuEntries({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memberships = ref.watch(myMembershipsProvider).value ?? const [];
    return Column(children: [
      Card(
        child: ListTile(
          leading: const Icon(Icons.build_circle_outlined),
          title: const Text('Service jobs'),
          subtitle: const Text('Get help with a problem and prepare a contractor visit'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => context.go('/service-jobs'),
        ),
      ),
      if (memberships.isNotEmpty)
        Card(
          child: ListTile(
            leading: const Icon(Icons.inbox_outlined),
            title: const Text('Contractor inbox'),
            subtitle: Text('Jobs and invitations for ${memberships.map((m) => m.name).join(', ')}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.go('/contractor/inbox'),
          ),
        ),
    ]);
  }
}

/// Vessel-screen entry points: "Get help with a problem" and "Understand an invoice".
class VesselServiceActions extends StatelessWidget {
  const VesselServiceActions({super.key, required this.vesselId});

  final String vesselId;

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 12, runSpacing: 12, children: [
      ElevatedButton.icon(
        onPressed: () => context.go(Uri(
          path: '/service-jobs/new',
          queryParameters: {'vessel_id': vesselId, 'entry': 'vessel'},
        ).toString()),
        icon: const Icon(Icons.build_circle_outlined),
        label: const Text('Get help with a problem'),
      ),
      OutlinedButton.icon(
        onPressed: () => context.go(Uri(path: '/invoices/new', queryParameters: {'vessel_id': vesselId}).toString()),
        icon: const Icon(Icons.receipt_long_outlined),
        label: const Text('Understand an invoice'),
      ),
    ]);
  }
}
