import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class VesselDetailScreen extends ConsumerWidget {
  final String vesselId;

  const VesselDetailScreen({super.key, required this.vesselId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselState = ref.watch(vesselDetailProvider(vesselId));

    return Scaffold(
      appBar: AppBar(
        title: vesselState.whenOrNull(data: (v) => Text(v.name)) ??
            const Text('Vessel Details'),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit),
            onPressed: () => context.go('/vessels/$vesselId/edit'),
          ),
          IconButton(
            icon: const Icon(Icons.chat),
            tooltip: 'Ask First Mate about this vessel',
            onPressed: () => context.go('/vessels/$vesselId/chat'),
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: () => _confirmDelete(context, ref),
          ),
        ],
      ),
      body: vesselState.when(
        data: (vessel) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Vessel image / placeholder
            Container(
              height: 200,
              decoration: BoxDecoration(
                color: HelmTheme.primary.withOpacity(0.1),
                borderRadius: BorderRadius.circular(16),
              ),
              child: vessel.imageUrl != null
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Image.network(vessel.imageUrl!, fit: BoxFit.cover),
                    )
                  : const Center(
                      child: Icon(Icons.directions_boat,
                          size: 80, color: HelmTheme.primary),
                    ),
            ),
            const SizedBox(height: 24),

            // Vessel info
            Text(
              vessel.name,
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            if (vessel.isPrimary) ...[
              const SizedBox(height: 8),
              Chip(
                label: const Text('Primary Vessel'),
                backgroundColor: HelmTheme.primary.withOpacity(0.1),
                labelStyle: const TextStyle(color: HelmTheme.primary),
              ),
            ],
            const SizedBox(height: 24),

            // Specifications
            _SectionTitle(title: 'Specifications'),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    _DetailRow(label: 'Make', value: vessel.make),
                    _DetailRow(label: 'Model', value: vessel.model),
                    if (vessel.year != null)
                      _DetailRow(label: 'Year', value: vessel.year.toString()),
                    if (vessel.hullMaterial != null)
                      _DetailRow(
                          label: 'Hull Material', value: vessel.hullMaterial!),
                    if (vessel.lengthFt != null)
                      _DetailRow(
                          label: 'Length',
                          value: '${vessel.lengthFt!.toStringAsFixed(1)} ft'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Engine
            if (vessel.engineType != null ||
                vessel.engineMake != null ||
                vessel.engineModel != null) ...[
              _SectionTitle(title: 'Engine'),
              const SizedBox(height: 8),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: [
                      if (vessel.engineType != null)
                        _DetailRow(label: 'Type', value: vessel.engineType!),
                      if (vessel.engineMake != null)
                        _DetailRow(label: 'Make', value: vessel.engineMake!),
                      if (vessel.engineModel != null)
                        _DetailRow(label: 'Model', value: vessel.engineModel!),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ],

            // Actions
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => context.go('/vessels/$vesselId/chat'),
                    icon: const Icon(Icons.chat),
                    label: const Text('Ask First Mate'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => context.go('/products'),
                    icon: const Icon(Icons.shopping_bag),
                    label: const Text('Find Parts'),
                  ),
                ),
              ],
            ),
          ],
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Text('Failed to load vessel: $error'),
        ),
      ),
    );
  }

  void _confirmDelete(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Vessel'),
        content: const Text(
            'Are you sure you want to remove this vessel from your garage?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () async {
              Navigator.pop(context);
              await ref.read(vesselListProvider.notifier).deleteVessel(vesselId);
              if (context.mounted) context.go('/vessels');
            },
            style: TextButton.styleFrom(foregroundColor: HelmTheme.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;

  const _SectionTitle({required this.title});

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: Theme.of(context)
          .textTheme
          .titleMedium
          ?.copyWith(fontWeight: FontWeight.bold),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.grey[600])),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}
