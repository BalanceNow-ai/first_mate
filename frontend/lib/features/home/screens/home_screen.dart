import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final vessels = ref.watch(vesselListProvider);
    final cart = ref.watch(cartProvider).value;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Helm Marine'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out',
            onPressed: () => ref.read(authControllerProvider.notifier).signOut(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(vesselListProvider);
          ref.invalidate(cartProvider);
        },
        child: ContentWidth(
          maxWidth: 960,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _WelcomeBanner(name: user?.fullName ?? 'Skipper'),
              const SizedBox(height: 24),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _QuickAction(
                    icon: Icons.directions_boat,
                    label: 'My Vessels',
                    onTap: () => context.go('/vessels'),
                  ),
                  _QuickAction(
                    icon: Icons.storefront,
                    label: 'Shop parts',
                    onTap: () => context.go('/products'),
                  ),
                  _QuickAction(
                    icon: Icons.shopping_cart,
                    label: cart == null || cart.isEmpty
                        ? 'Cart'
                        : 'Cart · ${cart.itemCount} (${formatCents(cart.subtotalCents)})',
                    onTap: () => context.go('/cart'),
                  ),
                  _QuickAction(
                    icon: Icons.chat,
                    label: 'First Mate',
                    onTap: () => context.go('/chat'),
                  ),
                  _QuickAction(
                    icon: Icons.stars,
                    label: 'Crew Rewards',
                    onTap: () => context.go('/crew'),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              Semantics(
                header: true,
                child: Text('My Vessels',
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
              ),
              const SizedBox(height: 12),
              vessels.when(
                data: (list) {
                  if (list.isEmpty) {
                    return Card(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(
                          children: [
                            const Icon(Icons.directions_boat_outlined,
                                size: 48, color: HelmTheme.mutedText),
                            const SizedBox(height: 12),
                            const Text('Add your boat to see parts that fit it.'),
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
                    children: [
                      for (final v in list)
                        Card(
                          child: ListTile(
                            leading: const Icon(Icons.directions_boat, color: HelmTheme.primary),
                            title: Text(v.nickname),
                            subtitle: Text(v.description),
                            trailing: v.isPrimary ? const Chip(label: Text('Primary')) : null,
                            onTap: () => context.go('/vessels/${v.id}'),
                          ),
                        ),
                    ],
                  );
                },
                loading: () => const Padding(
                  padding: EdgeInsets.all(24),
                  child: LoadingView(message: 'Loading vessels'),
                ),
                error: (e, _) => ErrorView(
                  error: e,
                  title: 'Could not load vessels',
                  onRetry: () => ref.invalidate(vesselListProvider),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WelcomeBanner extends StatelessWidget {
  const _WelcomeBanner({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [HelmTheme.navy, HelmTheme.ocean],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Kia ora, $name',
            style: Theme.of(context)
                .textTheme
                .titleLarge
                ?.copyWith(color: Colors.white, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Text(
            'Parts, advice and checklists matched to your boat.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.white),
          ),
        ],
      ),
    );
  }
}

class _QuickAction extends StatelessWidget {
  const _QuickAction({required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 140, maxWidth: 220, minHeight: 88),
      child: Card(
        margin: EdgeInsets.zero,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 28, color: HelmTheme.ocean),
                const SizedBox(height: 8),
                Text(
                  label,
                  textAlign: TextAlign.center,
                  style: Theme.of(context)
                      .textTheme
                      .bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
