import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/widgets/service_menu_entries.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/features/vessels/widgets/equipment_section.dart';
import 'package:helm_marine/features/vessels/widgets/hin_suggestion.dart';
import 'package:helm_marine/features/vessels/widgets/service_section.dart';

class VesselDetailScreen extends ConsumerWidget {
  const VesselDetailScreen({super.key, required this.vesselId});

  final String vesselId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselState = ref.watch(vesselDetailProvider(vesselId));

    return DefaultTabController(
      length: 3,
      child: Scaffold(
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
          bottom: vesselState.hasValue
              ? const TabBar(
                  isScrollable: true,
                  labelColor: Colors.white,
                  unselectedLabelColor: Colors.white70,
                  indicatorColor: HelmTheme.seafoam,
                  tabs: [
                    Tab(text: 'Overview'),
                    Tab(text: 'Equipment'),
                    Tab(text: 'Service'),
                  ],
                )
              : null,
        ),
        body: vesselState.when(
          data: (vessel) => TabBarView(
            children: [
              ContentWidth(maxWidth: 900, child: _VesselDetails(vessel: vessel)),
              ContentWidth(maxWidth: 900, child: EquipmentSection(vessel: vessel)),
              ContentWidth(maxWidth: 900, child: ServiceSection(vessel: vessel)),
            ],
          ),
          loading: () => const LoadingView(message: 'Loading vessel'),
          error: (error, _) => ErrorView(
            error: error,
            title: 'Could not load this vessel',
            onRetry: () => ref.invalidate(vesselDetailProvider(vesselId)),
          ),
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
          'history are removed too.',
        ),
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
                  Text(
                    vessel.nickname,
                    style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
                  ),
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
        _Section(
          title: 'Vessel',
          rows: [
            ('Make', vessel.make),
            ('Model', vessel.model),
            ('Year', '${vessel.year}'),
            if (vessel.hullType != null) ('Hull', enumLabel(vessel.hullType!)),
            if (vessel.lengthFt != null) ('Length', '${_trim(vessel.lengthFt!)} ft'),
            if (vessel.propulsionType != null) ('Propulsion', enumLabel(vessel.propulsionType!)),
            if (vessel.primaryUse != null) ('Primary use', vessel.primaryUse!),
            if (vessel.hin != null)
              ('HIN', vessel.hinStatus == null ? vessel.hin! : '${vessel.hin!} (${vessel.hinStatus})'),
          ],
        ),
        const SizedBox(height: 16),
        _BoatDatabaseLink(vessel: vessel),
        if (vessel.hinDecoded != null) ...[const SizedBox(height: 16), _StoredHin(vessel: vessel)],
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
              onPressed: () => context.go(
                Uri(
                  path: '/products',
                  queryParameters: {'vessel_id': vessel.id, 'compatible_only': 'true'},
                ).toString(),
              ),
              icon: const Icon(Icons.storefront),
              label: const Text('Find compatible parts'),
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
        const SizedBox(height: 12),
        VesselServiceActions(vesselId: vessel.id),
      ],
    );
  }

  static String _trim(double v) => v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
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
              child: Text(
                title,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
              ),
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

/// The boat-database model year this vessel is linked to (if any).
class _BoatDatabaseLink extends ConsumerWidget {
  const _BoatDatabaseLink({required this.vessel});

  final Vessel vessel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = vessel.modelYearId;
    if (id == null) {
      return const _Section(
        title: 'Boat database',
        rows: [],
        empty:
            'Not linked to a boat-database model year. '
            'It links automatically when make, model and year exactly match an entry.',
      );
    }
    final detail = ref.watch(modelYearDetailProvider(id));
    return detail.when(
      loading: () => const _Section(title: 'Boat database', rows: [], empty: 'Loading linked model year…'),
      error: (e, _) =>
          const _Section(title: 'Boat database', rows: [], empty: 'Could not load the linked model year.'),
      data: (BoatModelYearDetail y) => _Section(
        title: 'Boat database',
        rows: [
          ('Linked model', y.label),
          if (y.boatModel.lengthFt != null) ('Model length', '${y.boatModel.lengthFt} ft'),
          ('Factory records', '${y.equipmentCount}'),
          if (y.isSynthetic) ('Data', 'Synthetic test data — not a real boat model'),
        ],
      ),
    );
  }
}

/// The HIN decode stored with the vessel (a suggestion, never applied).
class _StoredHin extends StatelessWidget {
  const _StoredHin({required this.vessel});

  final Vessel vessel;

  @override
  Widget build(BuildContext context) {
    try {
      return HinSuggestionCard(decode: HinDecode.fromJson(vessel.hinDecoded!));
    } on FormatException {
      return const SizedBox.shrink();
    }
  }
}
