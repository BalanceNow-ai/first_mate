import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_provider.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateProvider);
    final vesselsState = ref.watch(vesselListProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Helm Marine'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authStateProvider.notifier).signOut(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(vesselListProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Welcome banner
            _WelcomeBanner(
              userName: authState.valueOrNull?.fullName ?? 'Skipper',
            ),
            const SizedBox(height: 24),

            // Quick actions
            Text(
              'Quick Actions',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _QuickActionCard(
                    icon: Icons.directions_boat,
                    label: 'My Vessels',
                    color: HelmTheme.primary,
                    onTap: () => context.go('/vessels'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _QuickActionCard(
                    icon: Icons.shopping_bag,
                    label: 'Products',
                    color: HelmTheme.secondary,
                    onTap: () => context.go('/products'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _QuickActionCard(
                    icon: Icons.chat,
                    label: 'First Mate',
                    color: HelmTheme.accent,
                    onTap: () => context.go('/chat'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),

            // Vessel summary
            Text(
              'My Vessels',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 12),
            vesselsState.when(
              data: (vessels) {
                if (vessels.isEmpty) {
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          Icon(Icons.directions_boat_outlined,
                              size: 48, color: Colors.grey[400]),
                          const SizedBox(height: 12),
                          const Text('No vessels added yet'),
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            onPressed: () => context.go('/vessels/new'),
                            icon: const Icon(Icons.add),
                            label: const Text('Add Vessel'),
                          ),
                        ],
                      ),
                    ),
                  );
                }
                return Column(
                  children: vessels
                      .map((vessel) => Card(
                            child: ListTile(
                              leading: const Icon(Icons.directions_boat,
                                  color: HelmTheme.primary),
                              title: Text(vessel.name),
                              subtitle: Text(
                                  '${vessel.make} ${vessel.model}${vessel.year != null ? ' (${vessel.year})' : ''}'),
                              trailing: vessel.isPrimary
                                  ? const Chip(label: Text('Primary'))
                                  : null,
                              onTap: () =>
                                  context.go('/vessels/${vessel.id}'),
                            ),
                          ))
                      .toList(),
                );
              },
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (error, _) => Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text('Failed to load vessels: $error'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WelcomeBanner extends StatelessWidget {
  final String userName;

  const _WelcomeBanner({required this.userName});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [HelmTheme.primary, HelmTheme.primaryLight],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Welcome back, $userName!',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            'Your one-stop shop for marine parts and accessories in New Zealand.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Colors.white70,
                ),
          ),
        ],
      ),
    );
  }
}

class _QuickActionCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _QuickActionCard({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            children: [
              Icon(icon, size: 32, color: color),
              const SizedBox(height: 8),
              Text(
                label,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
