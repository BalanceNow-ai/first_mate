import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class VesselListScreen extends ConsumerWidget {
  const VesselListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselsState = ref.watch(vesselListProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('My Vessels')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.go('/vessels/new'),
        icon: const Icon(Icons.add),
        label: const Text('Add vessel'),
        tooltip: 'Add a vessel',
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(vesselListProvider),
        child: vesselsState.when(
          data: (vessels) {
            if (vessels.isEmpty) {
              return ListView(
                padding: const EdgeInsets.all(32),
                children: [
                  const Icon(Icons.directions_boat_outlined, size: 80, color: HelmTheme.mutedText),
                  const SizedBox(height: 16),
                  Text('No vessels in your garage',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  const Text(
                    'Add your first vessel to see which parts fit it.',
                    textAlign: TextAlign.center,
                  ),
                ],
              );
            }
            return ContentWidth(
              child: ListView.builder(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                itemCount: vessels.length,
                itemBuilder: (context, index) {
                  final vessel = vessels[index];
                  return Card(
                    margin: const EdgeInsets.only(bottom: 12),
                    child: ListTile(
                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                      leading: CircleAvatar(
                        backgroundColor: HelmTheme.primary.withValues(alpha: 0.12),
                        child: const Icon(Icons.directions_boat, color: HelmTheme.primary),
                      ),
                      title: Text(vessel.nickname,
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                      subtitle: Text([
                        vessel.description,
                        if (vessel.hasEngine)
                          [vessel.engineMake, vessel.engineModel].whereType<String>().join(' '),
                      ].join('\n')),
                      isThreeLine: vessel.hasEngine,
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (vessel.isPrimary)
                            const Chip(
                              label: Text('Primary'),
                              visualDensity: VisualDensity.compact,
                            ),
                          const Icon(Icons.chevron_right),
                        ],
                      ),
                      onTap: () => context.go('/vessels/${vessel.id}'),
                    ),
                  );
                },
              ),
            );
          },
          loading: () => const LoadingView(message: 'Loading vessels'),
          error: (error, _) => ErrorView(
            error: error,
            title: 'Could not load vessels',
            onRetry: () => ref.invalidate(vesselListProvider),
          ),
        ),
      ),
    );
  }
}
