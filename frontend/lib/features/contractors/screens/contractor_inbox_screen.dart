import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/contractors/providers/contractor_providers.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// `/contractor/inbox`: my organizations, invitations to review (admins) and assigned jobs.
class ContractorInboxScreen extends ConsumerWidget {
  const ContractorInboxScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memberships = ref.watch(myMembershipsProvider);
    final inbox = ref.watch(contractorInboxProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Contractor inbox'),
        actions: [
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(myMembershipsProvider);
              ref.invalidate(contractorInboxProvider);
            },
          ),
        ],
      ),
      body: ContentWidth(
        maxWidth: 900,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            AsyncSection<List<MyMembership>>(
              value: memberships,
              onRetry: () => ref.invalidate(myMembershipsProvider),
              builder: (list) => list.isEmpty
                  ? const InfoNote(
                      'You are not a member of a contractor organisation. Organisations are set up by Helm; '
                      'ask your administrator to add you.',
                    )
                  : SectionCard(title: 'Your organisations', children: [
                      for (final m in list)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.business),
                          title: Text(m.name),
                          subtitle: Text(memberRoleLabels[m.role] ?? humanise(m.role)),
                          trailing: m.isAdmin ? const Icon(Icons.chevron_right) : null,
                          onTap: m.isAdmin ? () => context.go('/contractor/organizations/${m.organizationId}') : null,
                        ),
                    ]),
            ),
            AsyncSection<ContractorInbox>(
              value: inbox,
              onRetry: () => ref.invalidate(contractorInboxProvider),
              builder: (box) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (box.invitations.isNotEmpty)
                  SectionCard(
                    title: 'Invitations to review',
                    subtitle: 'You see only a summary until your organisation accepts and assigns people.',
                    children: [for (final i in box.invitations) _InvitationTile(invitation: i)],
                  ),
                SectionCard(
                  title: 'Jobs assigned to you',
                  children: [
                    if (box.assigned.isEmpty) const Text('No jobs assigned to you yet.'),
                    for (final j in box.assigned)
                      Card(
                        color: HelmTheme.surface,
                        margin: const EdgeInsets.only(bottom: 8),
                        child: ListTile(
                          title: Text(j.title),
                          subtitle: Text('${j.organizationName} · ${jobStatusLabel(j.status)} · updated ${formatDateTime(j.updatedAt)}'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => context.go('/contractor/jobs/${j.jobId}'),
                        ),
                      ),
                  ],
                ),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}

class _InvitationTile extends StatelessWidget {
  const _InvitationTile({required this.invitation});

  final InvitationSummary invitation;

  @override
  Widget build(BuildContext context) {
    final i = invitation;
    return Card(
      color: HelmTheme.surface,
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text(i.jobTitle),
        subtitle: Text([
          if (i.vesselLine.isNotEmpty) i.vesselLine,
          if (i.inviterFirstName != null) 'from ${i.inviterFirstName}',
          'invited ${formatDateTime(i.invitedAt)}',
          '${i.sections.length} section(s) shared',
        ].join(' · ')),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.go('/contractor/organizations/${i.organizationId}'),
      ),
    );
  }
}
