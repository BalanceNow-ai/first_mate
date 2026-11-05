import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class VesselDetailScreen extends ConsumerWidget {
  const VesselDetailScreen({super.key, required this.vesselId});

  final String vesselId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselState = ref.watch(vesselDetailProvider(vesselId));

    return Scaffold(
      appBar: AppBar(
        title: Text(vesselState.value?.nickname ?? 'Vessel'),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit),
            tooltip: 'Edit vessel',
            onPressed: () => context.go('/vessels/$vesselId/edit'),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: 'Delete vessel',
            onPressed: () => _confirmDelete(context, ref),
          ),
        ],
      ),
      body: vesselState.when(
        data: (vessel) => ContentWidth(child: _VesselDetails(vessel: vessel)),
        loading: () => const LoadingView(message: 'Loading vessel'),
        error: (error, _) => ErrorView(
          error: error,
          title: 'Could not load this vessel',
          onRetry: () => ref.invalidate(vesselDetailProvider(vesselId)),
        ),
      ),
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete vessel'),
        content: const Text(
            'Remove this vessel from your garage? Its equipment, checklists and service '
            'history are removed too.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: HelmTheme.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(vesselListProvider.notifier).deleteVessel(vesselId);
      if (context.mounted) context.go('/vessels');
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not delete vessel');
    }
  }
}

class _VesselDetails extends StatelessWidget {
  const _VesselDetails({required this.vessel});

  final Vessel vessel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: HelmTheme.primary.withValues(alpha: 0.12),
              child: const Icon(Icons.directions_boat, size: 32, color: HelmTheme.primary),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(vessel.nickname,
                      style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                  Text(vessel.description, style: theme.textTheme.bodyLarge),
                  if (vessel.isPrimary) ...[
                    const SizedBox(height: 4),
                    const Chip(label: Text('Primary vessel')),
                  ],
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        _Section(title: 'Vessel', rows: [
          ('Make', vessel.make),
          ('Model', vessel.model),
          ('Year', '${vessel.year}'),
          if (vessel.hullType != null) ('Hull', enumLabel(vessel.hullType!)),
          if (vessel.lengthFt != null) ('Length', '${_trim(vessel.lengthFt!)} ft'),
          if (vessel.propulsionType != null) ('Propulsion', enumLabel(vessel.propulsionType!)),
          if (vessel.primaryUse != null) ('Primary use', vessel.primaryUse!),
          if (vessel.hin != null) ('HIN', vessel.hin!),
        ]),
        const SizedBox(height: 16),
        _Section(
          title: 'Engine',
          rows: [
            if (vessel.engineMake != null) ('Make', vessel.engineMake!),
            if (vessel.engineModel != null) ('Model', vessel.engineModel!),
            if (vessel.engineYear != null) ('Year', '${vessel.engineYear}'),
            if (vessel.engineHours != null) ('Hours', '${vessel.engineHours} h'),
            if (vessel.engineSerial != null) ('Serial', vessel.engineSerial!),
          ],
          empty: 'No engine details yet — add them so we can check part fitment.',
        ),
        const SizedBox(height: 24),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            ElevatedButton.icon(
              onPressed: () => context.go('/products'),
              icon: const Icon(Icons.storefront),
              label: const Text('Find parts'),
            ),
            OutlinedButton.icon(
              onPressed: () => context.go('/vessels/${vessel.id}/chat'),
              icon: const Icon(Icons.chat),
              label: const Text('Ask First Mate'),
            ),
            OutlinedButton.icon(
              onPressed: () => context.go('/vessels/${vessel.id}/checklists'),
              icon: const Icon(Icons.checklist),
              label: const Text('Voyage checklists'),
            ),
          ],
        ),
      ],
    );
  }

  static String _trim(double v) =>
      v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.rows, this.empty});

  final String title;
  final List<(String, String)> rows;
  final String? empty;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text(title,
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 8),
            if (rows.isEmpty && empty != null) Text(empty!),
            for (final (label, value) in rows)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 120,
                      child: Text(label, style: const TextStyle(color: HelmTheme.mutedText)),
                    ),
                    Expanded(
                      child: Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
