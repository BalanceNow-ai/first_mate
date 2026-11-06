import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/contractors/providers/contractor_providers.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

const _defaultSections = ['summary', 'evidence', 'measurements', 'preparation', 'access_general', 'scope'];

/// What the live-updates choice means (the server's preview note gives the exact wording).
const liveUpdatesOffExplanation =
    'Off (recommended): they see the job as of the brief you publish — not your later changes — plus what '
    'their own organisation records. Until you publish a brief they see only the job title and status.';
const liveUpdatesOnExplanation =
    'On: they see the sections you share as they are now, including every change you make later.';

/// The live-updates switch, explained in plain words (off by default).
class LiveUpdatesChoice extends StatelessWidget {
  const LiveUpdatesChoice({super.key, required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Live updates'),
        subtitle: Text(value ? liveUpdatesOnExplanation : liveUpdatesOffExplanation),
        value: value,
        onChanged: onChanged,
      ),
      const Text(
        'Either way, evidence requests and your answers, scope proposals and decisions, visits and any invoice '
        'question you choose to send stay up to date.',
        style: TextStyle(color: HelmTheme.mutedText, fontSize: 12),
      ),
    ]);
  }
}

/// Owner: choose who receives what, preview it exactly, and manage access.
class SharingTab extends ConsumerWidget {
  const SharingTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assignments = ref.watch(assignmentsProvider(job.id));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const InfoNote(
          'You decide who sees this job. A contractor sees only the sections you choose, inside Helm — '
          'nothing is emailed. Revoking stops new access immediately; copies already downloaded cannot be recalled.',
        ),
        AsyncSection<List<Assignment>>(
          value: assignments,
          onRetry: () => ref.invalidate(assignmentsProvider(job.id)),
          builder: (list) {
            final live = list.where((a) => a.isLive).firstOrNull;
            final past = list.where((a) => !a.isLive).toList();
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (live != null)
                _LiveAssignment(job: job, assignment: live)
              else if (!job.isClosed)
                _InviteCard(job: job),
              if (past.isNotEmpty)
                SectionCard(title: 'Earlier contractors', children: [
                  for (final a in past)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(a.organization.displayName),
                      subtitle: Text('${assignmentStatusLabel(a.status)} · invited ${formatDate(a.invitedAt)}'),
                    ),
                ]),
            ]);
          },
        ),
        _AccessDetailsCard(job: job),
      ],
    );
  }
}

class _LiveAssignment extends ConsumerWidget {
  const _LiveAssignment({required this.job, required this.assignment});

  final ServiceJob job;
  final Assignment assignment;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final a = assignment;
    final api = ref.read(serviceJobsApiProvider);
    return SectionCard(
      title: 'Shared with ${a.organization.displayName}',
      children: [
        StatusBadge(assignmentStatusLabel(a.status), tone: a.status == 'accepted' ? Tone.good : Tone.info),
        const SizedBox(height: 8),
        const Text('Sections they can see:', style: TextStyle(fontWeight: FontWeight.w600)),
        BulletList([for (final s in a.sections) sectionLabel(s)]),
        FactRow(
            'Live updates',
            a.liveUpdates
                ? 'On — they see the shared sections as they are now, including later changes'
                : 'Off — they see the job as of the brief you publish'),
        FactRow('Invited', formatDateTime(a.invitedAt)),
        if (a.acceptedAt != null) FactRow('Accepted', formatDateTime(a.acceptedAt!)),
        if (a.members.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text('Assigned people', style: TextStyle(fontWeight: FontWeight.w600)),
          if (!a.sections.contains('access_restricted'))
            const Text('Access credentials are not shared, so nobody can be authorised to see them.',
                style: TextStyle(color: HelmTheme.mutedText)),
          for (final m in a.members)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(m.name ?? 'Member'),
              subtitle: const Text('May see gate codes, keys, contacts and exact location'),
              value: m.restrictedAccess,
              onChanged: a.sections.contains('access_restricted')
                  ? (v) => runJobAction(context, ref, job.id,
                      () => api.setMemberRestrictedAccess(job.id, a.id, m.userId, v, a.version),
                      success: v ? '${m.name ?? 'Member'} may now see access credentials' : 'Access credentials withdrawn')
                  : null,
            ),
        ] else if (a.status == 'accepted')
          const Text('Their administrator has not assigned anyone yet.'),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          ActionButton(
            label: 'Change shared sections',
            icon: Icons.tune,
            onPressed: () async {
              final result = await showDialog<(List<String>, bool)>(
                context: context,
                builder: (_) => _SectionsDialog(initial: a.sections, liveUpdates: a.liveUpdates),
              );
              if (result == null || !context.mounted) return;
              await runJobAction(context, ref, job.id,
                  () => api.updateSharing(job.id, a.id, a.version, sections: result.$1, liveUpdates: result.$2),
                  success: 'Sharing updated');
            },
          ),
          ActionButton(
            label: 'Reassign to another organisation',
            icon: Icons.swap_horiz,
            onPressed: () async {
              final pick = await showDialog<DirectoryEntry>(context: context, builder: (_) => const _DirectoryDialog());
              if (pick == null || !context.mounted) return;
              final ok = await confirmAction(context,
                  title: 'Reassign to ${pick.displayName}?',
                  message: '${a.organization.displayName} loses access immediately and ${pick.displayName} is invited '
                      'with the same sections.',
                  confirm: 'Reassign');
              if (!ok || !context.mounted) return;
              await runJobAction(context, ref, job.id,
                  () => api.reassign(job.id, a.id, pick.id, a.sections, a.liveUpdates,
                      idempotencyKey: newIdempotencyKey('reassign')),
                  success: 'Reassigned');
            },
          ),
          ActionButton(
            label: 'Revoke access',
            icon: Icons.block,
            tone: Tone.bad,
            onPressed: () async {
              final reason = await promptText(context,
                  title: 'Revoke ${a.organization.displayName}?',
                  label: 'Reason (optional)',
                  message: 'Their next request is refused. Signed links already issued expire within 5 minutes.',
                  required: false,
                  confirm: 'Revoke access',
                  maxLength: 500);
              if (reason == null || !context.mounted) return;
              await runJobAction(context, ref, job.id, () => api.revoke(job.id, a.id, reason: reason),
                  success: 'Access revoked');
            },
          ),
        ]),
      ],
    );
  }
}

/// Pick an organization and sections, preview exactly what they will see, then send.
class _InviteCard extends ConsumerStatefulWidget {
  const _InviteCard({required this.job});

  final ServiceJob job;

  @override
  ConsumerState<_InviteCard> createState() => _InviteCardState();
}

class _InviteCardState extends ConsumerState<_InviteCard> {
  final _search = TextEditingController();
  String _query = '';
  DirectoryEntry? _org;
  final Set<String> _sections = {..._defaultSections};
  bool _liveUpdates = false;
  SharingPreview? _preview;
  String? _inviteKey;
  bool _busy = false;

  List<String> get _ordered => [for (final s in shareableSections) if (_sections.contains(s)) s];

  void _changed() => setState(() {
        _preview = null;
        _inviteKey = null;
      });

  Future<void> _previewNow() async {
    if (_org == null || _sections.isEmpty) return;
    setState(() => _busy = true);
    try {
      final p = await ref.read(serviceJobsApiProvider).previewSharing(widget.job.id, _org!.id, _ordered, _liveUpdates);
      setState(() {
        _preview = p;
        _inviteKey = newIdempotencyKey('invite');
      });
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not prepare the preview');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _send() async {
    setState(() => _busy = true);
    await runJobAction(
      context,
      ref,
      widget.job.id,
      () => ref.read(serviceJobsApiProvider).invite(widget.job.id, _org!.id, _ordered, _liveUpdates,
          idempotencyKey: _inviteKey!),
      success: 'Invitation sent to ${_org!.displayName}',
    );
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final results = ref.watch(directoryProvider(_query));
    return SectionCard(
      title: 'Invite a contractor',
      subtitle: 'Being listed gives an organisation no access — only your invitation does.',
      children: [
        TextField(
          controller: _search,
          decoration: InputDecoration(
            labelText: 'Search organisations',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: IconButton(
              tooltip: 'Search',
              icon: const Icon(Icons.arrow_forward),
              onPressed: () => setState(() => _query = _search.text.trim()),
            ),
          ),
          onSubmitted: (v) => setState(() => _query = v.trim()),
        ),
        const SizedBox(height: 8),
        results.when(
          loading: () => const LinearProgressIndicator(),
          error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(directoryProvider(_query))),
          data: (page) => page.items.isEmpty
              ? const Text('No organisations match.')
              : RadioGroup<String>(
                  groupValue: _org?.id,
                  onChanged: (id) {
                    _org = page.items.firstWhere((o) => o.id == id);
                    _changed();
                  },
                  child: Column(children: [
                    for (final o in page.items)
                      RadioListTile<String>(value: o.id, title: Text(o.displayName), contentPadding: EdgeInsets.zero),
                    LoadMoreButton(
                      hasMore: page.hasMore,
                      loadingMore: page.loadingMore,
                      error: page.moreError,
                      label: 'More organisations',
                      onLoadMore: () => ref.read(directoryProvider(_query).notifier).loadMore(),
                    ),
                  ]),
                ),
        ),
        const Divider(height: 24),
        const Text('Choose what they can see', style: TextStyle(fontWeight: FontWeight.w600)),
        for (final s in shareableSections)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            title: Text(sectionLabel(s)),
            subtitle: s == 'access_restricted'
                ? const Text('Shown only to people you individually authorise after they accept.')
                : null,
            value: _sections.contains(s),
            onChanged: (v) {
              v == true ? _sections.add(s) : _sections.remove(s);
              _changed();
            },
          ),
        const Divider(height: 24),
        const Text('How they see the job', style: TextStyle(fontWeight: FontWeight.w600)),
        LiveUpdatesChoice(
          value: _liveUpdates,
          onChanged: (v) {
            _liveUpdates = v;
            _changed();
          },
        ),
        const SizedBox(height: 8),
        ActionButton(
          label: 'Preview what they will see',
          icon: Icons.visibility_outlined,
          onPressed: _org == null || _sections.isEmpty || _busy ? null : _previewNow,
        ),
        if (_org == null) const Text('Choose an organisation first.', style: TextStyle(color: HelmTheme.mutedText)),
        if (_preview != null) ...[
          const SizedBox(height: 12),
          SharingPreviewView(preview: _preview!),
          ActionButton(
            label: 'Send invitation',
            icon: Icons.send,
            filled: true,
            onPressed: _busy ? null : _send,
          ),
        ],
      ],
    );
  }
}

/// Exactly what an organization would receive: section labels, field names and counts.
class SharingPreviewView extends StatelessWidget {
  const SharingPreviewView({super.key, required this.preview});

  final SharingPreview preview;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: HelmTheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: HelmTheme.primary.withValues(alpha: 0.4)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Semantics(
          header: true,
          container: true,
          child: Text('Preview: what ${preview.organization.displayName} will see',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
        ),
        const SizedBox(height: 8),
        for (final s in preview.sections) ...[
          Text(s.label, style: const TextStyle(fontWeight: FontWeight.w600)),
          if (s.exposes.isNotEmpty) Text('Includes: ${s.exposes.map(humanise).join(', ')}'),
          if (s.counts.isNotEmpty) Text(s.counts.entries.map((e) => '${humanise(e.key)}: ${e.value}').join(' · ')),
          if (s.note != null) Text(s.note!, style: const TextStyle(fontStyle: FontStyle.italic)),
          const SizedBox(height: 8),
        ],
        if (preview.withheld.isNotEmpty) ...[
          const Text('Not shared:', style: TextStyle(fontWeight: FontWeight.w600)),
          Text(preview.withheld.map(sectionLabel).join(' · ')),
          const SizedBox(height: 8),
        ],
        Semantics(
          container: true,
          label: 'Live updates ${preview.liveUpdates ? 'on' : 'off'}: ${preview.liveUpdatesNote}',
          excludeSemantics: true,
          child: InfoNote(
            '${preview.liveUpdates ? 'Live updates on' : 'Live updates off'}: ${preview.liveUpdatesNote}',
            icon: preview.liveUpdates ? Icons.sync : Icons.description_outlined,
          ),
        ),
      ]),
    );
  }
}

class _SectionsDialog extends StatefulWidget {
  const _SectionsDialog({required this.initial, required this.liveUpdates});

  final List<String> initial;
  final bool liveUpdates;

  @override
  State<_SectionsDialog> createState() => _SectionsDialogState();
}

class _SectionsDialogState extends State<_SectionsDialog> {
  late final Set<String> _sections = {...widget.initial};
  late bool _live = widget.liveUpdates;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Shared sections'),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final s in shareableSections)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(sectionLabel(s)),
                value: _sections.contains(s),
                onChanged: (v) => setState(() => v == true ? _sections.add(s) : _sections.remove(s)),
              ),
            LiveUpdatesChoice(value: _live, onChanged: (v) => setState(() => _live = v)),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: _sections.isEmpty
              ? null
              : () => Navigator.pop(context, ([for (final s in shareableSections) if (_sections.contains(s)) s], _live)),
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _DirectoryDialog extends ConsumerStatefulWidget {
  const _DirectoryDialog();

  @override
  ConsumerState<_DirectoryDialog> createState() => _DirectoryDialogState();
}

class _DirectoryDialogState extends ConsumerState<_DirectoryDialog> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final results = ref.watch(directoryProvider(_query));
    return AlertDialog(
      title: const Text('Choose an organisation'),
      content: SizedBox(
        width: 420,
        height: 360,
        child: Column(children: [
          TextField(
            decoration: const InputDecoration(labelText: 'Search organisations', prefixIcon: Icon(Icons.search)),
            onSubmitted: (v) => setState(() => _query = v.trim()),
          ),
          Expanded(
            child: results.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Text(describeErrorText(e)),
              data: (page) => ListView(children: [
                for (final o in page.items)
                  ListTile(title: Text(o.displayName), onTap: () => Navigator.pop(context, o)),
                LoadMoreButton(
                  hasMore: page.hasMore,
                  loadingMore: page.loadingMore,
                  error: page.moreError,
                  label: 'More organisations',
                  onLoadMore: () => ref.read(directoryProvider(_query).notifier).loadMore(),
                ),
              ]),
            ),
          ),
        ]),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel'))],
    );
  }
}

String describeErrorText(Object e) => friendlyTitle(e);

/// Access and logistics (general) and credentials (restricted, separately).
class _AccessDetailsCard extends ConsumerWidget {
  const _AccessDetailsCard({required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final general = ref.watch(accessGeneralProvider(job.id));
    return SectionCard(
      title: 'Access and logistics',
      subtitle: 'Only what the contractor needs. Gate codes, keys, contacts and exact location are kept separate.',
      children: [
        AsyncSection<AccessDetails>(
          value: general,
          onRetry: () => ref.invalidate(accessGeneralProvider(job.id)),
          builder: (d) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final e in accessGeneralFields.entries)
              if ((d.values[e.key] ?? '').isNotEmpty) FactRow(e.value, d.values[e.key]!),
            if (d.values.values.every((v) => v == null || v.isEmpty)) const Text('Nothing recorded yet.'),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              ActionButton(
                label: 'Edit access and logistics',
                icon: Icons.edit_location_alt_outlined,
                onPressed: job.isClosed
                    ? null
                    : () async {
                        final values = await showDialog<Map<String, String?>>(
                          context: context,
                          builder: (_) => _FieldsDialog(title: 'Access and logistics', fields: accessGeneralFields, values: d.values),
                        );
                        if (values == null || !context.mounted) return;
                        await runJobAction(context, ref, job.id,
                            () => ref.read(serviceJobsApiProvider).putAccessGeneral(job.id, d.version, values),
                            success: 'Access details saved');
                      },
              ),
              ActionButton(
                label: 'Access credentials',
                icon: Icons.lock_outline,
                onPressed: () => showDialog<void>(context: context, builder: (_) => _RestrictedDialog(job: job, version: d.version)),
              ),
            ]),
          ]),
        ),
      ],
    );
  }
}

class _RestrictedDialog extends ConsumerWidget {
  const _RestrictedDialog({required this.job, required this.version});

  final ServiceJob job;
  final int version;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final restricted = ref.watch(accessRestrictedProvider(job.id));
    return AlertDialog(
      title: const Text('Access credentials and exact location'),
      content: SizedBox(
        width: 440,
        child: restricted.when(
          loading: () => const SizedBox(height: 80, child: Center(child: CircularProgressIndicator())),
          error: (e, _) => Text(friendlyTitle(e)),
          data: (d) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Revealed only to assigned people you authorise. Never included in feedback or notifications.'),
            const SizedBox(height: 8),
            for (final e in accessRestrictedFields.entries)
              if ((d.values[e.key] ?? '').isNotEmpty) FactRow(e.value, d.values[e.key]!),
            if (d.values.values.every((v) => v == null || v.isEmpty)) const Text('Nothing recorded yet.'),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
        if (restricted.hasValue && !job.isClosed)
          FilledButton(
            onPressed: () async {
              final d = restricted.value!;
              final values = await showDialog<Map<String, String?>>(
                context: context,
                builder: (_) => _FieldsDialog(title: 'Access credentials', fields: accessRestrictedFields, values: d.values),
              );
              if (values == null || !context.mounted) return;
              await runJobAction(context, ref, job.id,
                  () => ref.read(serviceJobsApiProvider).putAccessRestricted(job.id, d.version, values),
                  success: 'Credentials saved');
              ref.invalidate(accessRestrictedProvider(job.id));
            },
            child: const Text('Edit'),
          ),
      ],
    );
  }
}

class _FieldsDialog extends StatefulWidget {
  const _FieldsDialog({required this.title, required this.fields, required this.values});

  final String title;
  final Map<String, String> fields;
  final Map<String, String?> values;

  @override
  State<_FieldsDialog> createState() => _FieldsDialogState();
}

class _FieldsDialogState extends State<_FieldsDialog> {
  late final Map<String, TextEditingController> _c = {
    for (final k in widget.fields.keys) k: TextEditingController(text: widget.values[k]),
  };

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final e in widget.fields.entries)
              TextField(
                controller: _c[e.key],
                maxLength: accessFieldMaxLengths[e.key] ?? 100,
                decoration: InputDecoration(labelText: e.value),
              ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () => Navigator.pop(context, {
            for (final e in _c.entries) e.key: e.value.text.trim().isEmpty ? null : e.value.text.trim(),
          }),
          child: const Text('Save'),
        ),
      ],
    );
  }
}
