import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/content/data/content_api.dart';
import 'package:helm_marine/features/content/widgets/articles_section.dart';
import 'package:helm_marine/features/home/data/home_api.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

/// Signed-in home: the primary vessel, quick links, an in-progress Helm Dash
/// delivery and content hub articles — only real server data, no invented stats.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final vessels = ref.watch(vesselListProvider);
    final delivery = ref.watch(activeDeliveryProvider).value;
    final list = vessels.value ?? const <Vessel>[];
    Vessel? primary;
    for (final v in list) {
      if (v.isPrimary) primary ??= v;
    }
    primary ??= list.isEmpty ? null : list.first;

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
          ref.invalidate(activeDeliveryProvider);
          ref.invalidate(articlesProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            ContentWidth(
              maxWidth: 960,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _WelcomeBanner(name: user?.fullName?.trim().isNotEmpty == true ? user!.fullName! : 'Skipper'),
                  if (delivery != null) ...[const SizedBox(height: 16), _DeliveryCard(delivery: delivery)],
                  const SizedBox(height: 16),
                  vessels.when(
                    data: (_) => primary == null ? const _AddVesselCard() : _PrimaryVesselCard(vessel: primary),
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
                  const SizedBox(height: 24),
                  Semantics(
                    header: true,
                    child: Text('Quick links',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _QuickAction(icon: Icons.directions_boat, label: 'Garage', onTap: () => context.go('/vessels')),
                      _QuickAction(
                        icon: Icons.verified,
                        label: 'Parts that fit',
                        onTap: () => context.go('/products?compatible_only=true'),
                      ),
                      _QuickAction(icon: Icons.chat, label: 'First Mate', onTap: () => context.go('/chat')),
                      _QuickAction(
                        icon: Icons.checklist,
                        label: 'Checklists',
                        onTap: () =>
                            context.go(primary == null ? '/vessels' : '/vessels/${primary.id}/checklists'),
                      ),
                      _QuickAction(icon: Icons.receipt_long, label: 'Orders', onTap: () => context.go('/profile')),
                      _QuickAction(icon: Icons.stars, label: 'Crew Rewards', onTap: () => context.go('/crew')),
                      if (user?.role == 'admin')
                        _QuickAction(
                          icon: Icons.admin_panel_settings,
                          label: 'Admin console',
                          onTap: () => context.go('/admin'),
                        ),
                    ],
                  ),
                  const ArticlesSection(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PrimaryVesselCard extends StatelessWidget {
  const _PrimaryVesselCard({required this.vessel});

  final Vessel vessel;

  @override
  Widget build(BuildContext context) {
    final v = vessel;
    final engine = [v.engineMake, v.engineModel].whereType<String>().join(' ');
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.directions_boat, color: HelmTheme.primary, size: 32),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(v.nickname, style: Theme.of(context).textTheme.titleLarge),
                      Text([v.description, if (engine.isNotEmpty) engine].join(' · ')),
                    ],
                  ),
                ),
                if (v.isPrimary) const Chip(label: Text('Primary')),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: () => context.go('/vessels/${v.id}'),
                  icon: const Icon(Icons.info_outline),
                  label: const Text('Vessel details'),
                ),
                OutlinedButton.icon(
                  onPressed: () => context.go('/vessels/${v.id}/chat'),
                  icon: const Icon(Icons.chat_outlined),
                  label: const Text('Ask about this boat'),
                ),
                OutlinedButton.icon(
                  onPressed: () => context.go('/vessels/${v.id}/checklists'),
                  icon: const Icon(Icons.checklist),
                  label: const Text('Checklists'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _AddVesselCard extends StatelessWidget {
  const _AddVesselCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const Icon(Icons.directions_boat_outlined, size: 48, color: HelmTheme.mutedText),
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
}

class _DeliveryCard extends StatelessWidget {
  const _DeliveryCard({required this.delivery});

  final DeliverySummary delivery;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      color: HelmTheme.seafoam.withValues(alpha: 0.12),
      child: ListTile(
        leading: const Icon(Icons.delivery_dining, color: HelmTheme.secondary),
        title: Text('Helm Dash delivery: ${delivery.statusLabel}'),
        subtitle: Text('Order ${delivery.orderNumber}'
            '${delivery.estimatedDeliveryMinutes == null ? '' : ' · about ${delivery.estimatedDeliveryMinutes} min'}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.go('/dash/${delivery.id}'),
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
            style: Theme.of(context).textTheme.titleLarge?.copyWith(color: Colors.white, fontWeight: FontWeight.bold),
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
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 28, color: HelmTheme.ocean),
                const SizedBox(height: 8),
                Text(label,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
