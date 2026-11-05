import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/content/widgets/synthetic_badge.dart';
import 'package:helm_marine/features/loyalty/data/loyalty_api.dart';
import 'package:helm_marine/features/loyalty/providers/loyalty_provider.dart';
import 'package:intl/intl.dart';

final _points = NumberFormat.decimalPattern('en_NZ');
final _date = DateFormat('d MMM y');

String formatPoints(int points) => '${_points.format(points)} CP';

String _title(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1).replaceAll('_', ' ');

/// Explains why the CMS catalogue is unavailable (server reason codes).
String catalogueReasonText(String? reason) => switch (reason) {
      'cms_disabled' => 'The experiences catalogue is switched off. (cms_disabled)',
      'cms_not_configured' => 'The experiences catalogue has not been set up yet. (cms_not_configured)',
      'cms_unreachable' => 'The experiences catalogue could not be reached. Please try again later. (cms_unreachable)',
      'fixture_not_permitted' => 'Test fixtures are not permitted in this environment. (fixture_not_permitted)',
      null => 'The experiences catalogue could not be loaded.',
      _ => 'The experiences catalogue is unavailable ($reason).',
    };

String _multiplier(double m) => '${m.toStringAsFixed(m == m.roundToDouble() ? 1 : 2)}×';

/// Crew Rewards: points, ledger, multiplier progress, crew, discounts and
/// Signature Experiences — every number comes from the server.
class CrewDashboardScreen extends StatelessWidget {
  const CrewDashboardScreen({super.key, this.initialTab = 0});

  final int initialTab;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      initialIndex: initialTab,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Crew Rewards'),
          bottom: const TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            indicatorColor: HelmTheme.seafoam,
            tabs: [
              Tab(text: 'Points'),
              Tab(text: 'Crew'),
              Tab(text: 'Redeem'),
              Tab(text: 'Experiences'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [_PointsTab(), _CrewTab(), _RedeemTab(), _ExperiencesTab()],
        ),
      ),
    );
  }
}

/// Common scrolling body with pull-to-refresh and readable width.
class _TabBody extends StatelessWidget {
  const _TabBody({required this.onRefresh, required this.children});

  final Future<void> Function() onRefresh;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ContentWidth(
            maxWidth: 820,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 8),
        child: Semantics(
          header: true,
          child: Text(text, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
        ),
      );
}

Widget _asyncCard<T>(AsyncValue<T> value, String what, VoidCallback retry, Widget Function(T) data) =>
    value.when(
      data: data,
      loading: () => Padding(padding: const EdgeInsets.all(24), child: LoadingView(message: 'Loading $what')),
      error: (e, _) => ErrorView(error: e, title: 'Could not load $what', onRetry: retry),
    );

// ------------------------------------------------------------------- points tab
class _PointsTab extends ConsumerWidget {
  const _PointsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final points = ref.watch(pointsSummaryProvider);
    final crew = ref.watch(myCrewProvider);
    final multiplier = ref.watch(multiplierProgressProvider);
    final ledger = ref.watch(transactionLedgerProvider);
    return _TabBody(
      onRefresh: () async => refreshRewards(ref),
      children: [
        _asyncCard(points, 'points', () => ref.invalidate(pointsSummaryProvider), (p) => _PointsCard(points: p)),
        if (points.value?.crewWalletPoints != null)
          _CrewWalletCard(points: points.value!.crewWalletPoints!, crew: crew.value),
        const _SectionTitle('Monthly crew multiplier'),
        _asyncCard(multiplier, 'multiplier progress', () => ref.invalidate(multiplierProgressProvider),
            (m) => _MultiplierCard(progress: m)),
        const _SectionTitle('Points activity'),
        _asyncCard(ledger, 'points activity', () => ref.invalidate(transactionLedgerProvider),
            (l) => _LedgerList(ledger: l)),
      ],
    );
  }
}

class _PointsCard extends StatelessWidget {
  const _PointsCard({required this.points});

  final PointsSummary points;

  @override
  Widget build(BuildContext context) {
    final p = points;
    final threshold = p.nextTierThresholdCents;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(colors: [HelmTheme.navy, HelmTheme.ocean]),
        borderRadius: BorderRadius.circular(16),
      ),
      child: DefaultTextStyle.merge(
        style: const TextStyle(color: Colors.white),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Your Crew Points', style: TextStyle(fontSize: 14)),
            const SizedBox(height: 4),
            Semantics(
              label: 'Balance ${formatPoints(p.pointsBalance)}, worth ${p.valueText}',
              excludeSemantics: true,
              child: Text(formatPoints(p.pointsBalance),
                  style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w900, color: Colors.white)),
            ),
            Text('Worth ${p.valueText} in discounts · ${formatPoints(p.lifetimeEarned)} earned in total'),
            if (p.pointsOwed > 0) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(8)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.info_outline, size: 18, color: Colors.white),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text('${formatPoints(p.pointsOwed)} owed from a refunded order — '
                          'settled from your next points'),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Chip(
                  avatar: const Icon(Icons.workspace_premium, size: 18),
                  label: Text('${_title(p.tier)} tier'),
                ),
                if (p.tierIsDisplayOnly)
                  const Text(
                    'Tiers are recognition only — they do not change prices or how points are earned.',
                    style: TextStyle(fontSize: 12, color: Colors.white70),
                  ),
              ],
            ),
            if (p.nextTier != null && threshold != null && threshold > 0) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(
                value: (p.trailing12MonthSpendCents / threshold).clamp(0.0, 1.0),
                backgroundColor: Colors.white24,
                color: HelmTheme.seafoam,
                semanticsLabel: 'Progress to ${_title(p.nextTier!)} tier',
              ),
              const SizedBox(height: 4),
              Text(
                '${formatCents(p.trailing12MonthSpendCents)} paid spend in the last 12 months · '
                '${formatCents(max(0, threshold - p.trailing12MonthSpendCents))} to ${_title(p.nextTier!)}',
                style: const TextStyle(fontSize: 12, color: Colors.white70),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CrewWalletCard extends StatelessWidget {
  const _CrewWalletCard({required this.points, required this.crew});

  final int points;
  final Crew? crew;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: ListTile(
        leading: const Icon(Icons.account_balance_wallet_outlined, color: HelmTheme.ocean),
        title: Text('Crew Wallet: ${formatPoints(points)}'),
        subtitle: Text(crew?.walletNote ??
            "The Crew Wallet shows members' combined balances; each member redeems only their own points."),
      ),
    );
  }
}

class _MultiplierCard extends StatelessWidget {
  const _MultiplierCard({required this.progress});

  final MultiplierProgress progress;

  @override
  Widget build(BuildContext context) {
    final m = progress;
    final String status;
    if (m.crewId == null) {
      status = 'Join or create a crew of at least ${m.minMembers} members to earn a monthly multiplier.';
    } else if (!m.eligibleForMultiplier) {
      status = 'Your crew needs at least ${m.minMembers} members to earn the multiplier '
          '(${m.memberCount} now).';
    } else {
      status = 'Your crew qualifies for the multiplier this month.';
    }
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Semantics(
                  label: 'Current multiplier ${_multiplier(m.currentMultiplier)}',
                  excludeSemantics: true,
                  child: Text(_multiplier(m.currentMultiplier),
                      style: const TextStyle(fontSize: 36, fontWeight: FontWeight.w900, color: HelmTheme.ocean)),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Period ${m.period}', style: const TextStyle(fontWeight: FontWeight.bold)),
                      Text('Crew spend this month: ${formatCents(m.crewSpendCents, currency: m.currency)} '
                          '(paid orders only)'),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(status),
            if (m.nextThresholdCents != null && m.nextMultiplier != null) ...[
              const SizedBox(height: 12),
              LinearProgressIndicator(value: m.progressToNext, semanticsLabel: 'Progress to next multiplier'),
              const SizedBox(height: 4),
              Text('${formatCents(m.remainingToNextCents ?? 0, currency: m.currency)} more paid spend this month '
                  'reaches ${_multiplier(m.nextMultiplier!)}'),
            ],
            const SizedBox(height: 12),
            Table(
              columnWidths: const {0: FlexColumnWidth(2), 1: FlexColumnWidth(1)},
              children: [
                const TableRow(children: [
                  Padding(padding: EdgeInsets.all(4), child: Text('Monthly crew spend', style: TextStyle(fontWeight: FontWeight.bold))),
                  Padding(padding: EdgeInsets.all(4), child: Text('Multiplier', style: TextStyle(fontWeight: FontWeight.bold))),
                ]),
                for (final t in m.tiers)
                  TableRow(
                    decoration: t.multiplier == m.spendMultiplier
                        ? BoxDecoration(color: HelmTheme.seafoam.withValues(alpha: 0.15))
                        : null,
                    children: [
                      Padding(padding: const EdgeInsets.all(4), child: Text('${formatCents(t.minSpendCents)}+')),
                      Padding(padding: const EdgeInsets.all(4), child: Text(_multiplier(t.multiplier))),
                    ],
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _LedgerList extends ConsumerWidget {
  const _LedgerList({required this.ledger});

  final TransactionLedger ledger;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ledger.items.isEmpty) {
      return const Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Text('No points activity yet. Points are earned on paid orders.'),
        ),
      );
    }
    return Card(
      margin: EdgeInsets.zero,
      child: Column(
        children: [
          for (final t in ledger.items)
            ListTile(
              title: Text(t.kindLabel),
              subtitle: Text([if (t.description != null) t.description!, _date.format(t.createdAt.toLocal())].join(' · ')),
              trailing: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text('${t.points > 0 ? '+' : ''}${_points.format(t.points)}',
                      style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: t.points >= 0 ? HelmTheme.success : HelmTheme.error)),
                  Text('Balance ${_points.format(t.balanceAfter)}', style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          if (ledger.moreError != null)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(describeError(ledger.moreError!), style: const TextStyle(color: HelmTheme.error)),
            ),
          if (ledger.hasMore)
            Padding(
              padding: const EdgeInsets.all(8),
              child: OutlinedButton(
                onPressed: ledger.loadingMore ? null : () => ref.read(transactionLedgerProvider.notifier).loadMore(),
                child: Text(ledger.loadingMore
                    ? 'Loading…'
                    : 'Load more (${ledger.items.length} of ${ledger.total})'),
              ),
            ),
        ],
      ),
    );
  }
}

// --------------------------------------------------------------------- crew tab
class _CrewTab extends ConsumerWidget {
  const _CrewTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final crew = ref.watch(myCrewProvider);
    final inbox = ref.watch(myInvitesProvider);
    final pending = (inbox.value ?? const <MyInvite>[]).where((i) => i.status == 'pending').toList();
    return _TabBody(
      onRefresh: () async => refreshCrew(ref),
      children: [
        if (inbox.hasError)
          ErrorView(error: inbox.error!, title: 'Could not load your invites', onRetry: () => ref.invalidate(myInvitesProvider)),
        if (pending.isNotEmpty) ...[
          const _SectionTitle('Crew invites for you'),
          for (final i in pending) _InviteInboxCard(invite: i, inCrew: crew.value != null),
        ],
        _asyncCard(crew, 'your crew', () => ref.invalidate(myCrewProvider),
            (c) => c == null ? const _CreateCrewCard() : _CrewCard(crew: c)),
      ],
    );
  }
}

/// Runs [action], refreshes crew views and reports success or the server error.
Future<T?> _act<T>(BuildContext context, WidgetRef ref, Future<T> Function() action, String done,
    {bool rewards = false}) async {
  try {
    final result = await action();
    refreshCrew(ref);
    if (rewards) refreshRewards(ref);
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
    return result;
  } catch (e) {
    if (context.mounted) showErrorSnackBar(context, e);
    return null;
  }
}

class _InviteInboxCard extends ConsumerWidget {
  const _InviteInboxCard({required this.invite, required this.inCrew});

  final MyInvite invite;
  final bool inCrew;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(loyaltyApiProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Join ${invite.crewName}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            Text([
              if (invite.invitedByName != null) 'Invited by ${invite.invitedByName}',
              'Expires ${_date.format(invite.expiresAt.toLocal())}',
            ].join(' · ')),
            if (inCrew)
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text('You are already in a crew — leave it before joining another.',
                    style: TextStyle(color: HelmTheme.mutedText)),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                FilledButton(
                  onPressed: () => _act(context, ref, () => api.acceptInvite(invite.id), 'Welcome aboard ${invite.crewName}'),
                  child: const Text('Accept invite'),
                ),
                OutlinedButton(
                  onPressed: () => _act(context, ref, () => api.declineInvite(invite.id), 'Invite declined'),
                  child: const Text('Decline'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CreateCrewCard extends ConsumerStatefulWidget {
  const _CreateCrewCard();

  @override
  ConsumerState<_CreateCrewCard> createState() => _CreateCrewCardState();
}

class _CreateCrewCardState extends ConsumerState<_CreateCrewCard> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    await _act(context, ref, () => ref.read(loyaltyApiProvider).createCrew(_name.text.trim()), 'Crew created');
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final minMembers = ref.watch(multiplierProgressProvider).value?.minMembers;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _form,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("You're not in a crew yet", style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(
                'Start a crew and invite your mates by email. '
                '${minMembers == null ? '' : 'Crews of $minMembers or more earn a monthly multiplier on paid spend. '}'
                'Everyone keeps and spends only their own points.',
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _name,
                maxLength: 60,
                decoration: const InputDecoration(labelText: 'Crew name'),
                validator: (v) => (v == null || v.trim().length < 2) ? 'Use at least 2 characters' : null,
                onFieldSubmitted: (_) => _create(),
              ),
              FilledButton.icon(
                onPressed: _busy ? null : _create,
                icon: const Icon(Icons.group_add),
                label: const Text('Create crew'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CrewCard extends ConsumerWidget {
  const _CrewCard({required this.crew});

  final Crew crew;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(loyaltyApiProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          margin: EdgeInsets.zero,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Semantics(
                  header: true,
                  child: Text(crew.name, style: Theme.of(context).textTheme.titleLarge),
                ),
                Text('${crew.iAmCaptain ? 'You are the captain' : 'You are a member'} · '
                    '${crew.memberCount} of ${crew.maxMembers} members'
                    '${crew.iAmCaptain && crew.pendingInviteCount > 0 ? ' · ${crew.pendingInviteCount} pending invites' : ''}'),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: HelmTheme.seafoam.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.account_balance_wallet_outlined, color: HelmTheme.secondary),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Crew Wallet: ${formatPoints(crew.walletPoints)}',
                                style: const TextStyle(fontWeight: FontWeight.bold)),
                            Text(crew.walletNote),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const _SectionTitle('Members'),
        Card(
          margin: EdgeInsets.zero,
          child: Column(
            children: [
              for (final m in crew.members)
                ListTile(
                  leading: CircleAvatar(child: Text(m.displayName.isEmpty ? '?' : m.displayName[0].toUpperCase())),
                  title: Wrap(
                    spacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(m.isYou ? '${m.displayName} (you)' : m.displayName),
                      if (m.isCaptain)
                        const InfoPill(label: 'Captain', icon: Icons.anchor, color: HelmTheme.navy),
                    ],
                  ),
                  subtitle: Text('${formatPoints(m.pointsBalance)} · joined ${_date.format(m.joinedAt.toLocal())}'),
                  trailing: crew.iAmCaptain && !m.isYou
                      ? IconButton(
                          icon: const Icon(Icons.person_remove_outlined),
                          tooltip: 'Remove ${m.displayName}',
                          onPressed: () async {
                            final ok = await _confirm(context, 'Remove ${m.displayName}?',
                                '${m.displayName} leaves the crew and keeps their own points.', 'Remove');
                            if (ok && context.mounted) {
                              await _act(context, ref, () => api.removeMember(m.userId), '${m.displayName} removed');
                            }
                          },
                        )
                      : null,
                ),
            ],
          ),
        ),
        if (crew.iAmCaptain) ...[
          const _SectionTitle('Invite a mate'),
          const _InviteForm(),
          const _PendingInvites(),
        ],
        const SizedBox(height: 20),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: HelmTheme.error),
            icon: const Icon(Icons.logout),
            label: const Text('Leave crew'),
            onPressed: () => _leave(context, ref),
          ),
        ),
      ],
    );
  }

  Future<void> _leave(BuildContext context, WidgetRef ref) async {
    final others = crew.members.where((m) => !m.isYou).toList()..sort((a, b) => a.joinedAt.compareTo(b.joinedAt));
    final String explanation;
    if (!crew.iAmCaptain) {
      explanation = 'You keep your own points. Your spend will no longer count towards ${crew.name}.';
    } else if (others.isEmpty) {
      explanation = "You're the only member, so ${crew.name} will be disbanded. You keep your own points.";
    } else {
      explanation = 'Captaincy passes to the longest-serving member (${others.first.displayName}). '
          'You keep your own points.';
    }
    final ok = await _confirm(context, 'Leave ${crew.name}?', explanation, 'Leave crew');
    if (!ok || !context.mounted) return;
    final result = await _act(context, ref, () => ref.read(loyaltyApiProvider).leaveCrew(), 'You left ${crew.name}');
    if (result != null && context.mounted) {
      String? name;
      for (final m in crew.members) {
        if (m.userId == result.newCaptainId) name = m.displayName;
      }
      final msg = result.disbanded
          ? '${crew.name} was disbanded.'
          : (name != null ? '$name is now the captain.' : null);
      if (msg != null) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    }
  }
}

Future<bool> _confirm(BuildContext context, String title, String body, String action) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: Text(action)),
        ],
      ),
    ) ??
    false;

class _InviteForm extends ConsumerStatefulWidget {
  const _InviteForm();

  @override
  ConsumerState<_InviteForm> createState() => _InviteFormState();
}

class _InviteFormState extends ConsumerState<_InviteForm> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    final email = _email.text.trim();
    final invite = await _act(context, ref, () => ref.read(loyaltyApiProvider).invite(email), 'Invite sent to $email');
    if (!mounted) return;
    setState(() => _busy = false);
    if (invite != null) _email.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _form,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: TextFormField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: const InputDecoration(labelText: 'Email address to invite'),
              validator: (v) => RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(v?.trim() ?? '')
                  ? null
                  : 'Enter an email address',
              onFieldSubmitted: (_) => _send(),
            ),
          ),
          const SizedBox(width: 8),
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: FilledButton(onPressed: _busy ? null : _send, child: const Text('Send invite')),
          ),
        ],
      ),
    );
  }
}

class _PendingInvites extends ConsumerWidget {
  const _PendingInvites();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final invites = ref.watch(crewInvitesProvider);
    return invites.when(
      loading: () => const Padding(padding: EdgeInsets.all(16), child: LoadingView(message: 'Loading invites')),
      error: (e, _) => ErrorView(error: e, title: 'Could not load invites', onRetry: () => ref.invalidate(crewInvitesProvider)),
      data: (list) {
        final pending = list.where((i) => i.status == 'pending').toList();
        if (pending.isEmpty) {
          return const Padding(padding: EdgeInsets.only(top: 8), child: Text('No pending invites.'));
        }
        return Card(
          margin: const EdgeInsets.only(top: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Text('Pending invites', style: TextStyle(fontWeight: FontWeight.bold)),
              ),
              for (final i in pending)
                ListTile(
                  title: Text(i.invitedEmail),
                  subtitle: Text('Expires ${_date.format(i.expiresAt.toLocal())}'),
                  trailing: TextButton(
                    onPressed: () => _act(context, ref, () => ref.read(loyaltyApiProvider).revokeInvite(i.id),
                        'Invite to ${i.invitedEmail} revoked'),
                    child: const Text('Revoke'),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

// ------------------------------------------------------------------- redeem tab
class _RedeemTab extends ConsumerWidget {
  const _RedeemTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final points = ref.watch(pointsSummaryProvider);
    final entitlements = ref.watch(entitlementsProvider);
    return _TabBody(
      onRefresh: () async => refreshRewards(ref),
      children: [
        _asyncCard(points, 'points', () => ref.invalidate(pointsSummaryProvider), (p) => _DiscountForm(points: p)),
        const _SectionTitle('Your discount codes'),
        _asyncCard(entitlements, 'discount codes', () => ref.invalidate(entitlementsProvider), (list) {
          if (list.isEmpty) {
            return const Card(
              margin: EdgeInsets.zero,
              child: Padding(padding: EdgeInsets.all(20), child: Text('No discount codes yet.')),
            );
          }
          return Card(
            margin: EdgeInsets.zero,
            child: Column(children: [for (final e in list) _EntitlementTile(entitlement: e)]),
          );
        }),
      ],
    );
  }
}

class _DiscountForm extends ConsumerStatefulWidget {
  const _DiscountForm({required this.points});

  final PointsSummary points;

  @override
  ConsumerState<_DiscountForm> createState() => _DiscountFormState();
}

class _DiscountFormState extends ConsumerState<_DiscountForm> {
  /// Redemption rate from the server (points per \$1); redemptions are whole dollars.
  int get step => widget.points.pointsPerDollar <= 0 ? 100 : widget.points.pointsPerDollar;
  final _form = GlobalKey<FormState>();
  late final _amount = TextEditingController(text: '$step');
  bool _busy = false;
  Entitlement? _result;
  String? _key;

  @override
  void initState() {
    super.initState();
    _amount.addListener(() => setState(() => _key = null));
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _redeem() async {
    if (!_form.currentState!.validate()) return;
    final points = int.parse(_amount.text.trim());
    // One key per intended redemption: a double tap returns the same code.
    _key ??= 'redeem-${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(0x3fffffff)}';
    setState(() => _busy = true);
    try {
      final e = await ref.read(loyaltyApiProvider).redeemDiscount(points, idempotencyKey: _key!);
      if (!mounted) return;
      setState(() {
        _result = e;
        _key = null;
      });
      refreshRewards(ref);
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not redeem');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final balance = widget.points.pointsBalance;
    final value = int.tryParse(_amount.text.trim());
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _form,
          autovalidateMode: AutovalidateMode.onUserInteraction,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Redeem for a discount', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text('$step Crew Points = \$1.00 off. Redeem in multiples of $step from your own balance '
                  '(${formatPoints(balance)} available).'),
              const SizedBox(height: 12),
              TextFormField(
                controller: _amount,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: InputDecoration(
                  labelText: 'Points to redeem',
                  helperText: value != null && value > 0 && value % step == 0
                      ? 'Worth ${formatCents(value * 100 ~/ step)} off'
                      : null,
                ),
                validator: (v) {
                  final n = int.tryParse(v?.trim() ?? '');
                  if (n == null || n < step) return 'Enter at least $step points';
                  if (n % step != 0) return 'Use a multiple of $step';
                  if (n > balance) return 'You have ${formatPoints(balance)}';
                  return null;
                },
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _busy || balance < step ? null : _redeem,
                icon: const Icon(Icons.redeem),
                label: const Text('Redeem points'),
              ),
              if (balance < step)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('You need at least 100 Crew Points to redeem. Points are earned on paid orders.'),
                ),
              if (_result != null) ...[
                const SizedBox(height: 16),
                Semantics(
                  liveRegion: true,
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: HelmTheme.success.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: HelmTheme.success),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.check_circle, color: HelmTheme.success),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Discount code ${_result!.code}', style: const TextStyle(fontWeight: FontWeight.bold)),
                              Text('${_result!.amountText} off your next order · ${formatPoints(_result!.pointsCost)} used'),
                            ],
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.copy),
                          tooltip: 'Copy code',
                          onPressed: () => Clipboard.setData(ClipboardData(text: _result!.code)),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

Color _statusColor(String status) => switch (status) {
      'issued' || 'requested' || 'pending' => HelmTheme.ocean,
      'confirmed' || 'reserved' => HelmTheme.warning,
      'fulfilled' || 'consumed' || 'approved' || 'admitted' || 'verified' || 'accepted' => HelmTheme.success,
      _ => HelmTheme.mutedText,
    };

class _EntitlementTile extends ConsumerWidget {
  const _EntitlementTile({required this.entitlement});

  final Entitlement entitlement;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final e = entitlement;
    return ListTile(
      title: Wrap(
        spacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SelectableText(e.code, style: const TextStyle(fontWeight: FontWeight.bold)),
          InfoPill(label: _title(e.status), color: _statusColor(e.status)),
        ],
      ),
      subtitle: Text('${e.amountText} off · ${formatPoints(e.pointsCost)} · ${_date.format(e.createdAt.toLocal())}'),
      trailing: e.canVoid
          ? TextButton(
              onPressed: () async {
                final ok = await _confirm(context, 'Void ${e.code}?',
                    'The code stops working and ${formatPoints(e.pointsCost)} return to your balance.', 'Void code');
                if (!ok || !context.mounted) return;
                try {
                  await ref.read(loyaltyApiProvider).voidEntitlement(e.id);
                  refreshRewards(ref);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${e.code} voided; points restored')));
                  }
                } catch (err) {
                  if (context.mounted) showErrorSnackBar(context, err);
                }
              },
              child: const Text('Void'),
            )
          : null,
    );
  }
}

// -------------------------------------------------------------- experiences tab
class _ExperiencesTab extends ConsumerWidget {
  const _ExperiencesTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final catalogue = ref.watch(experienceCatalogueProvider);
    final redemptions = ref.watch(myRedemptionsProvider);
    final balance = ref.watch(pointsSummaryProvider).value?.pointsBalance;
    return _TabBody(
      onRefresh: () async {
        ref.invalidate(experienceCatalogueProvider);
        refreshRewards(ref);
      },
      children: [
        _asyncCard(catalogue, 'Signature Experiences', () => ref.invalidate(experienceCatalogueProvider), (c) {
          if (!c.available) {
            return Card(
              margin: EdgeInsets.zero,
              child: ListTile(
                leading: const Icon(Icons.event_busy, color: HelmTheme.warning),
                title: const Text('Signature Experiences are unavailable right now'),
                subtitle: Text(catalogueReasonText(c.reason)),
              ),
            );
          }
          if (c.items.isEmpty) {
            return const Card(
              margin: EdgeInsets.zero,
              child: Padding(padding: EdgeInsets.all(20), child: Text('No Signature Experiences are listed.')),
            );
          }
          return Column(children: [for (final e in c.items) _ExperienceCard(experience: e, balance: balance)]);
        }),
        const _SectionTitle('My redemptions'),
        _asyncCard(redemptions, 'redemptions', () => ref.invalidate(myRedemptionsProvider), (list) {
          if (list.isEmpty) {
            return const Card(
              margin: EdgeInsets.zero,
              child: Padding(padding: EdgeInsets.all(20), child: Text('No experience redemptions yet.')),
            );
          }
          return Card(
            margin: EdgeInsets.zero,
            child: Column(children: [for (final r in list) RedemptionTile(redemption: r)]),
          );
        }),
      ],
    );
  }
}

/// One redemption record with its status.
class RedemptionTile extends StatelessWidget {
  const RedemptionTile({super.key, required this.redemption, this.trailing});

  final Redemption redemption;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final r = redemption;
    return ListTile(
      title: Wrap(
        spacing: 8,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(r.experienceTitle),
          InfoPill(label: _title(r.status), color: _statusColor(r.status)),
          if (r.isSynthetic) const SyntheticBadge(),
        ],
      ),
      subtitle: Text([
        formatPoints(r.pointsCost),
        'requested ${_date.format(r.createdAt.toLocal())}',
        if (r.fulfilledAt != null) 'fulfilled ${_date.format(r.fulfilledAt!.toLocal())}',
        if (r.customerNote != null) 'Note: ${r.customerNote}',
        if (r.staffNote != null) 'Staff note: ${r.staffNote}',
      ].join(' · ')),
      trailing: trailing,
      isThreeLine: trailing != null,
    );
  }
}

class _ExperienceCard extends ConsumerStatefulWidget {
  const _ExperienceCard({required this.experience, required this.balance});

  final Experience experience;
  final int? balance;

  @override
  ConsumerState<_ExperienceCard> createState() => _ExperienceCardState();
}

class _ExperienceCardState extends ConsumerState<_ExperienceCard> {
  bool _busy = false;

  /// One key per intended redemption, kept across retries after a failure so a
  /// repeated request can never debit points twice.
  String? _key;

  Experience get experience => widget.experience;
  int? get balance => widget.balance;

  @override
  Widget build(BuildContext context) {
    final e = experience;
    final short = balance != null && balance! < e.pointsCost;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(e.title, style: Theme.of(context).textTheme.titleMedium),
                if (e.isSynthetic) const SyntheticBadge(),
              ],
            ),
            const SizedBox(height: 4),
            Text(e.description),
            const SizedBox(height: 4),
            Text([
              formatPoints(e.pointsCost),
              if (e.location != null) e.location!,
              if (e.capacity != null) 'up to ${e.capacity} people',
            ].join(' · '), style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            if (!e.available)
              const Text('Not currently available', style: TextStyle(color: HelmTheme.mutedText))
            else
              Row(
                children: [
                  FilledButton(
                    onPressed: short || _busy ? null : () => _redeem(context),
                    child: Text(_busy ? 'Redeeming…' : 'Redeem experience'),
                  ),
                  if (short) ...[
                    const SizedBox(width: 12),
                    Expanded(child: Text('You need ${formatPoints(e.pointsCost - balance!)} more')),
                  ],
                ],
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _redeem(BuildContext context) async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Redeem ${experience.title}?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${formatPoints(experience.pointsCost)} will be taken from your own balance. '
                'The Helm team will contact you to confirm the booking; if it is cancelled your points are restored.'),
            const SizedBox(height: 12),
            TextField(
              controller: note,
              maxLength: 1000,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Note for the Helm team (optional)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Confirm redemption')),
        ],
      ),
    );
    final text = note.text;
    if (ok != true || !context.mounted || _busy) return;
    _key ??= 'exp-${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(0x3fffffff)}';
    setState(() => _busy = true);
    try {
      final r = await ref
          .read(loyaltyApiProvider)
          .redeemExperience(experience.id, note: text, idempotencyKey: _key!);
      _key = null;
      refreshRewards(ref);
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Redemption requested'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(r.experienceTitle, style: const TextStyle(fontWeight: FontWeight.bold)),
              Text('Status: ${_title(r.status)} · ${formatPoints(r.pointsCost)}'),
              if (r.customerNote != null) Text('Your note: ${r.customerNote}'),
              Text('Reference ${r.id.substring(0, 8)}'),
            ],
          ),
          actions: [FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('OK'))],
        ),
      );
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not redeem');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
