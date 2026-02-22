import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class VesselListScreen extends ConsumerWidget {
  const VesselListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselsState = ref.watch(vesselListProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('My Vessels'),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => context.go('/vessels/new'),
        backgroundColor: HelmTheme.primary,
        child: const Icon(Icons.add, color: Colors.white),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(vesselListProvider),
        child: vesselsState.when(
          data: (vessels) {
            if (vessels.isEmpty) {
              return Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.directions_boat_outlined,
                        size: 80, color: Colors.grey[300]),
                    const SizedBox(height: 16),
                    Text(
                      'No vessels in your garage',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Add your first vessel to get personalised\nproduct recommendations.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey[600]),
                    ),
                    const SizedBox(height: 24),
                    ElevatedButton.icon(
                      onPressed: () => context.go('/vessels/new'),
                      icon: const Icon(Icons.add),
                      label: const Text('Add Vessel'),
                    ),
                  ],
                ),
              );
            }

            return ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: vessels.length,
              itemBuilder: (context, index) {
                final vessel = vessels[index];
                return Card(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: InkWell(
                    onTap: () => context.go('/vessels/${vessel.id}'),
                    borderRadius: BorderRadius.circular(12),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Container(
                            width: 56,
                            height: 56,
                            decoration: BoxDecoration(
                              color: HelmTheme.primary.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: const Icon(Icons.directions_boat,
                                color: HelmTheme.primary),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        vessel.name,
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleSmall
                                            ?.copyWith(
                                                fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    if (vessel.isPrimary)
                                      Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 8,
                                          vertical: 2,
                                        ),
                                        decoration: BoxDecoration(
                                          color:
                                              HelmTheme.primary.withOpacity(0.1),
                                          borderRadius:
                                              BorderRadius.circular(12),
                                        ),
                                        child: const Text(
                                          'Primary',
                                          style: TextStyle(
                                            fontSize: 11,
                                            color: HelmTheme.primary,
                                            fontWeight: FontWeight.w600,
                                          ),
                                        ),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  '${vessel.make} ${vessel.model}${vessel.year != null ? ' (${vessel.year})' : ''}',
                                  style: TextStyle(color: Colors.grey[600]),
                                ),
                              ],
                            ),
                          ),
                          const Icon(Icons.chevron_right, color: Colors.grey),
                        ],
                      ),
                    ),
                  ),
                );
              },
            );
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.error_outline, size: 48, color: HelmTheme.error),
                const SizedBox(height: 16),
                Text('Failed to load vessels\n$error',
                    textAlign: TextAlign.center),
                const SizedBox(height: 16),
                ElevatedButton(
                  onPressed: () => ref.invalidate(vesselListProvider),
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
