import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/contractors/data/contractors_api.dart';
import 'package:helm_marine/features/contractors/providers/contractor_providers.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// `/contractor/organizations/:id`: an organization administrator accepts or
/// declines invitations and chooses which members work each job.
class ContractorOrgScreen extends ConsumerWidget {
  const ContractorOrgScreen({super.key, required this.orgId});

  final String orgId;

  void _refresh(WidgetRef ref) {
    ref.invalidate(orgInvitationsProvider(orgId));
    ref.invalidate(contractorInboxProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memberships = ref.watch(myMembershipsProvider).value ?? const [];
    final me = memberships.where((m) => m.organizationId == orgId).firstOrNull;
    final invitations = ref.watch(orgInvitationsProvider(orgId));
    final members = ref.watch(orgMembersProvider(orgId));
    return Scaffold(
      appBar: AppBar(
        title: Text(me?.name ?? 'Organisation'),
        leading: IconButton(
          tooltip: 'Back to contractor inbox',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/contractor/inbox'),
        ),
      ),
      body: ContentWidth(
        maxWidth: 900,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const InfoNote(
              'As an administrator you see a summary of each invitation. You see job content only if you assign '
              'yourself. Accepting does not accept any scope or price.',
            ),
            AsyncSection<List<InvitationSummary>>(
              value: invitations,
              onRetry: () => ref.invalidate(orgInvitationsProvider(orgId)),
              builder: (list) {
                final pending = list.where((i) => i.isPending).toList();
                final accepted = list.where((i) => i.status == 'accepted').toList();
                final other = list.where((i) => !i.isPending && i.status != 'accepted').toList();
                return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SectionCard(title: 'Waiting for your answer', children: [
                    if (pending.isEmpty) const Text('No pending invitations.'),
                    for (final i in pending)
                      _InvitationCard(orgId: orgId, invitation: i, members: members.value ?? const [], onChanged: () => _refresh(ref)),
                  ]),
                  if (accepted.isNotEmpty)
                    SectionCard(title: 'Accepted jobs', children: [
                      for (final i in accepted)
                        _InvitationCard(orgId: orgId, invitation: i, members: members.value ?? const [], onChanged: () => _refresh(ref)),
                    ]),
                  if (other.isNotEmpty)
                    SectionCard(title: 'Declined or revoked', children: [
                      for (final i in other)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(i.jobTitle),
                          subtitle: Text(assignmentStatusLabel(i.status)),
                        ),
                    ]),
                ]);
              },
            ),
            AsyncSection<List<OrgMember>>(
              value: members,
              onRetry: () => ref.invalidate(orgMembersProvider(orgId)),
              builder: (list) => SectionCard(title: 'Members', children: [
                for (final m in list)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.person_outline),
                    title: Text(m.displayName),
                    subtitle: Text('${memberRoleLabels[m.role] ?? m.role}${m.email == null ? '' : ' · ${m.email}'}'),
                  ),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}

class _InvitationCard extends ConsumerWidget {
  const _InvitationCard({required this.orgId, required this.invitation, required this.members, required this.onChanged});

  final String orgId;
  final InvitationSummary invitation;
  final List<OrgMember> members;
  final VoidCallback onChanged;

  Future<void> _run(BuildContext context, Future<void> Function() action, String success) async {
    try {
      await action();
      onChanged();
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(success)));
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final i = invitation;
    final api = ref.read(contractorsApiProvider);
    final assigned = {for (final m in i.members) m.userId};
    final active = members.where((m) => m.status == 'active').toList();
    return Card(
      color: HelmTheme.surface,
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(i.jobTitle, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          Text([
            if (i.vesselLine.isNotEmpty) i.vesselLine,
            if (i.inviterFirstName != null) 'from ${i.inviterFirstName}',
            'invited ${formatDateTime(i.invitedAt)}',
          ].join(' · ')),
          const SizedBox(height: 6),
          const Text('The owner would share:', style: TextStyle(fontWeight: FontWeight.w600)),
          BulletList([for (final s in i.sections) sectionLabel(s)]),
          if (i.members.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Assigned: ${i.members.map((m) => m.name ?? 'Member').join(', ')}'),
          ],
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (i.isPending) ...[
              ActionButton(
                label: 'Accept and assign people',
                icon: Icons.check,
                filled: true,
                onPressed: () async {
                  final ids = await showDialog<List<String>>(
                    context: context,
                    builder: (_) => _ChooseMembersDialog(members: active, initial: const {}),
                  );
                  if (ids == null || !context.mounted) return;
                  await _run(context, () => api.accept(i.assignmentId, ids), 'Invitation accepted');
                },
              ),
              ActionButton(
                label: 'Decline',
                tone: Tone.bad,
                onPressed: () async {
                  final ok = await confirmAction(context,
                      title: 'Decline this job?', message: 'The owner is told you declined.', confirm: 'Decline', destructive: true);
                  if (ok && context.mounted) await _run(context, () => api.decline(i.assignmentId), 'Invitation declined');
                },
              ),
            ],
            if (i.status == 'accepted') ...[
              ActionButton(
                label: 'Change assigned people',
                icon: Icons.group_outlined,
                onPressed: () async {
                  final ids = await showDialog<List<String>>(
                    context: context,
                    builder: (_) => _ChooseMembersDialog(members: active, initial: assigned),
                  );
                  if (ids == null || !context.mounted) return;
                  await _run(context, () async {
                    for (final id in ids.where((x) => !assigned.contains(x))) {
                      await api.addAssignmentMember(i.assignmentId, id);
                    }
                    for (final id in assigned.where((x) => !ids.contains(x))) {
                      await api.removeAssignmentMember(i.assignmentId, id);
                    }
                  }, 'Assigned people updated');
                },
              ),
              if (assigned.isNotEmpty)
                ActionButton(
                  label: 'Open job',
                  icon: Icons.open_in_new,
                  onPressed: () => context.go('/contractor/jobs/${i.jobId}'),
                ),
            ],
          ]),
        ]),
      ),
    );
  }
}

class _ChooseMembersDialog extends StatefulWidget {
  const _ChooseMembersDialog({required this.members, required this.initial});

  final List<OrgMember> members;
  final Set<String> initial;

  @override
  State<_ChooseMembersDialog> createState() => _ChooseMembersDialogState();
}

class _ChooseMembersDialogState extends State<_ChooseMembersDialog> {
  late final Set<String> _chosen = {...widget.initial};

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Who will work this job?'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Only the people you choose can open the job.'),
            for (final m in widget.members)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(m.displayName),
                subtitle: Text(memberRoleLabels[m.role] ?? m.role),
                value: _chosen.contains(m.userId),
                onChanged: (v) => setState(() => v == true ? _chosen.add(m.userId) : _chosen.remove(m.userId)),
              ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(context, _chosen.toList()), child: const Text('Confirm')),
      ],
    );
  }
}
