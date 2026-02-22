import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/loyalty/providers/loyalty_provider.dart';

class CrewDashboardScreen extends ConsumerWidget {
  const CrewDashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pointsState = ref.watch(crewPointsProvider);
    final multiplierState = ref.watch(crewMultiplierProvider);
    final teamsState = ref.watch(crewTeamsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Crew Rewards')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(crewPointsProvider);
          ref.invalidate(crewMultiplierProvider);
          ref.invalidate(crewTeamsProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Points Balance Card
            pointsState.when(
              data: (points) => _PointsCard(
                balance: points['points_balance'] as int? ?? 0,
                tier: points['tier'] as String? ?? 'deckhand',
              ),
              loading: () => const _LoadingCard(),
              error: (e, _) => _ErrorCard(message: 'Failed to load points: $e'),
            ),
            const SizedBox(height: 16),

            // Multiplier Card
            multiplierState.when(
              data: (data) {
                final monthlySpend =
                    (data['monthly_spend'] as num?)?.toDouble() ?? 0.0;
                final multiplier =
                    (data['multiplier'] as num?)?.toDouble() ?? 1.0;
                return _MultiplierCard(
                  monthlySpend: monthlySpend,
                  multiplier: multiplier,
                );
              },
              loading: () => const _LoadingCard(),
              error: (e, _) =>
                  _ErrorCard(message: 'Failed to load multiplier: $e'),
            ),
            const SizedBox(height: 24),

            // Crew Teams Section
            Text(
              'My Crew Teams',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            teamsState.when(
              data: (teams) {
                if (teams.isEmpty) {
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          Icon(Icons.group_outlined,
                              size: 48, color: Colors.grey[400]),
                          const SizedBox(height: 12),
                          const Text('No crew teams yet'),
                          const SizedBox(height: 8),
                          Text(
                            'Create a crew team to earn bonus multipliers\nwith your mates.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                                color: Colors.grey[600], fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                  );
                }
                return Column(
                  children: teams
                      .map((team) => Card(
                            margin: const EdgeInsets.only(bottom: 8),
                            child: ListTile(
                              leading: CircleAvatar(
                                backgroundColor:
                                    HelmTheme.secondary.withOpacity(0.15),
                                child: const Icon(Icons.group,
                                    color: HelmTheme.secondary),
                              ),
                              title: Text(team['name'] as String? ?? ''),
                              subtitle: Text(
                                '${team['member_count'] ?? 0} members',
                              ),
                              trailing: Text(
                                '${team['crew_wallet_balance'] ?? 0} CP',
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: HelmTheme.primary,
                                ),
                              ),
                            ),
                          ))
                      .toList(),
                );
              },
              loading: () => const _LoadingCard(),
              error: (e, _) =>
                  _ErrorCard(message: 'Failed to load teams: $e'),
            ),
            const SizedBox(height: 24),

            // Signature Experiences Section
            Text(
              'Signature Experiences',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            _ExperienceCard(
              title: 'Harbour Cruise',
              description:
                  'A guided harbour cruise around Auckland\'s Waitematā Harbour',
              costCp: 5000,
            ),
            const SizedBox(height: 8),
            _ExperienceCard(
              title: 'Fishing Charter',
              description:
                  'Full-day deep-sea fishing charter in the Hauraki Gulf',
              costCp: 15000,
            ),
            const SizedBox(height: 8),
            _ExperienceCard(
              title: 'Marine Detailing',
              description:
                  'Professional hull and topside detail for vessels up to 30ft',
              costCp: 8000,
            ),
          ],
        ),
      ),
    );
  }
}

class _PointsCard extends StatelessWidget {
  final int balance;
  final String tier;

  const _PointsCard({required this.balance, required this.tier});

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
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Crew Points',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: Colors.white70,
                    ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  tier.toUpperCase(),
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '$balance CP',
            style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 4),
          Text(
            'Worth \$${(balance / 100).toStringAsFixed(2)} NZD',
            style: const TextStyle(color: Colors.white60, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

class _MultiplierCard extends StatelessWidget {
  final double monthlySpend;
  final double multiplier;

  const _MultiplierCard({
    required this.monthlySpend,
    required this.multiplier,
  });

  @override
  Widget build(BuildContext context) {
    final tierName = getCurrentTierName(monthlySpend);
    final nextTier = getNextTier(monthlySpend);
    final progress = nextTier != null
        ? (monthlySpend / nextTier.minSpend).clamp(0.0, 1.0)
        : 1.0;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Points Multiplier',
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: HelmTheme.accent.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '${multiplier}x',
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      color: HelmTheme.accent,
                      fontSize: 16,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text('Current tier: $tierName',
                style: TextStyle(color: Colors.grey[600])),
            const SizedBox(height: 4),
            Text(
              'Monthly spend: \$${monthlySpend.toStringAsFixed(2)}',
              style: TextStyle(color: Colors.grey[600]),
            ),
            if (nextTier != null) ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: progress,
                        backgroundColor: Colors.grey[200],
                        valueColor: const AlwaysStoppedAnimation(HelmTheme.accent),
                        minHeight: 8,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    '\$${(nextTier.minSpend - monthlySpend).toStringAsFixed(0)} to ${nextTier.name}',
                    style: const TextStyle(fontSize: 12, color: HelmTheme.accent),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ExperienceCard extends StatelessWidget {
  final String title;
  final String description;
  final int costCp;

  const _ExperienceCard({
    required this.title,
    required this.description,
    required this.costCp,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: HelmTheme.accent.withOpacity(0.15),
          child: const Icon(Icons.star, color: HelmTheme.accent),
        ),
        title: Text(title),
        subtitle: Text(description, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '$costCp',
              style: const TextStyle(
                fontWeight: FontWeight.bold,
                color: HelmTheme.primary,
              ),
            ),
            const Text('CP', style: TextStyle(fontSize: 11)),
          ],
        ),
      ),
    );
  }
}

class _LoadingCard extends StatelessWidget {
  const _LoadingCard();

  @override
  Widget build(BuildContext context) {
    return const Card(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final String message;

  const _ErrorCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(message, style: const TextStyle(color: HelmTheme.error)),
      ),
    );
  }
}
