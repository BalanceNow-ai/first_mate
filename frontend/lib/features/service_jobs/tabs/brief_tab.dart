import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/tabs/requests_tab.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Owner: preview exactly what the assigned contractor will receive, then publish it.
class BriefTab extends ConsumerStatefulWidget {
  const BriefTab({super.key, required this.job});

  final ServiceJob job;

  @override
  ConsumerState<BriefTab> createState() => _BriefTabState();
}

class _BriefTabState extends ConsumerState<BriefTab> {
  Brief? _preview;
  bool _busy = false;

  ServiceJob get job => widget.job;

  Future<void> _makePreview() async {
    setState(() => _busy = true);
    try {
      final b = await ref.read(serviceJobsApiProvider).previewBrief(job.id);
      ref.invalidate(briefsProvider(job.id));
      setState(() => _preview = b);
    } catch (e) {
      if (!mounted) return;
      final api = ApiError.from(e);
      if (api?.code == 'no_live_assignment') {
        showErrorSnackBar(context, e, prefix: 'Invite a contractor on the Sharing tab first');
      } else {
        showErrorSnackBar(context, e, prefix: 'Could not prepare the preview');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _publish(Brief preview) async {
    final ok = await confirmAction(context,
        title: 'Publish revision ${preview.revisionNumber}?',
        message: '${preview.recipientName ?? 'The contractor'} will see exactly this revision. '
            'Later changes need a new revision.',
        confirm: 'Publish');
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    final published = await runJobAction(context, ref, job.id,
        () => ref.read(serviceJobsApiProvider).publishBrief(job.id, preview),
        success: 'Brief revision ${preview.revisionNumber} published');
    if (mounted) {
      setState(() {
        _busy = false;
        if (published != null) _preview = null;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final briefs = ref.watch(briefsProvider(job.id));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const InfoNote(
          '“Ready for contractor review” means enough information to review — not that the diagnosis or parts are '
          'correct. The contractor sees a published revision; preview it first.',
        ),
        if (!job.isClosed)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: ActionButton(
              label: _busy ? 'Working…' : 'Preview the brief',
              icon: Icons.visibility_outlined,
              filled: _preview == null,
              onPressed: _busy ? null : _makePreview,
            ),
          ),
        if (_preview != null) ...[
          SectionCard(
            title: 'Preview — revision ${_preview!.revisionNumber}',
            subtitle: 'For ${_preview!.recipientName ?? 'the assigned contractor'} · '
                '${_preview!.sections.map(sectionLabel).join(' · ')}',
            children: [
              BriefContentView(content: _preview!.content ?? const {}),
              const SizedBox(height: 8),
              ActionButton(
                label: 'Publish this revision',
                icon: Icons.publish,
                filled: true,
                onPressed: _busy ? null : () => _publish(_preview!),
              ),
            ],
          ),
        ],
        AsyncSection<List<Brief>>(
          value: briefs,
          onRetry: () => ref.invalidate(briefsProvider(job.id)),
          builder: (list) => SectionCard(
            title: 'Revisions',
            children: [
              if (list.isEmpty) const Text('No brief revisions yet.'),
              for (final b in list.reversed) BriefRevisionTile(brief: b),
            ],
          ),
        ),
      ],
    );
  }
}

class BriefRevisionTile extends StatelessWidget {
  const BriefRevisionTile({super.key, required this.brief});

  final Brief brief;

  @override
  Widget build(BuildContext context) {
    final b = brief;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text('Revision ${b.revisionNumber}'),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: 4),
        Wrap(spacing: 6, runSpacing: 6, children: [
          StatusBadge(humanise(b.status), tone: b.isPublished ? Tone.good : Tone.neutral, semanticPrefix: 'Brief'),
          if (b.isCurrent) const StatusBadge('Current', tone: Tone.info),
          if (b.outdated) const StatusBadge('Out of date', tone: Tone.warn),
        ]),
        if (b.publishedAt != null) Text('Published ${formatDateTime(b.publishedAt!)}'),
        for (final r in b.outdatedReasons) Text(outdatedReasonLabel(r)),
        for (final a in b.acknowledgements)
          Text('Contractor: ${ackKindLabel(a.kind)}${a.note == null ? '' : ' — “${a.note}”'} (${formatDateTime(a.createdAt)})'),
      ]),
    );
  }
}

/// Contractor: the latest published brief (read-only, with gaps) and acknowledgements.
class ContractorBriefTab extends ConsumerWidget {
  const ContractorBriefTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final briefs = ref.watch(briefsProvider(job.id));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _AccessPanel(job: job),
        AsyncSection<List<Brief>>(
          value: briefs,
          onRetry: () => ref.invalidate(briefsProvider(job.id)),
          builder: (list) {
            final published = list.where((b) => b.isPublished || b.status == 'superseded').toList();
            if (published.isEmpty) {
              return const InfoNote('The owner has not published a brief yet. You will see it here when they do.');
            }
            final latest = published.last;
            return _PublishedBrief(job: job, briefId: latest.id);
          },
        ),
      ],
    );
  }
}

class _PublishedBrief extends ConsumerWidget {
  const _PublishedBrief({required this.job, required this.briefId});

  final ServiceJob job;
  final String briefId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = (jobId: job.id, briefId: briefId);
    final brief = ref.watch(briefDetailProvider(key));
    final api = ref.read(serviceJobsApiProvider);
    return AsyncSection<Brief>(
      value: brief,
      onRetry: () => ref.invalidate(briefDetailProvider(key)),
      builder: (b) {
        Future<void> ack(String kind, {String? note, Map<String, dynamic>? view}) async {
          await runJobAction(context, ref, job.id,
              () => api.acknowledgeBrief(job.id, b.id, kind: kind, note: note, requestedView: view),
              success: kind == 'incomplete' ? 'Sent — the owner has been asked for the view' : 'Recorded: ${ackKindLabel(kind)}');
          ref.invalidate(briefDetailProvider(key));
        }

        return SectionCard(
          title: 'Brief — revision ${b.revisionNumber}',
          subtitle: [
            if (b.publishedAt != null) 'Published ${formatDateTime(b.publishedAt!)}',
            if (b.outdated) 'The owner has made changes since — a newer revision may follow',
          ].join(' · '),
          children: [
            BriefContentView(content: b.content ?? const {}),
            const Divider(height: 24),
            const Text('Your response', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final a in b.acknowledgements)
              Text('${ackKindLabel(a.kind)}${a.note == null ? '' : ' — “${a.note}”'} (${formatDateTime(a.createdAt)})'),
            const SizedBox(height: 8),
            if (!job.isClosed)
              Wrap(spacing: 8, runSpacing: 8, children: [
                ActionButton(label: 'Mark as reviewed', icon: Icons.done, onPressed: () => ack('reviewed')),
                ActionButton(
                  label: 'Acknowledge limitations',
                  icon: Icons.rule,
                  onPressed: () => ack('limitations_acknowledged'),
                ),
                ActionButton(
                  label: 'Request one more view',
                  icon: Icons.add_a_photo_outlined,
                  filled: true,
                  onPressed: () async {
                    final v = await askForView(context, title: 'Brief incomplete — request a view');
                    if (v == null || !context.mounted) return;
                    await ack('incomplete', note: v.prompt, view: v.toJson());
                  },
                ),
                ActionButton(
                  label: 'Confirm preparation',
                  icon: Icons.verified_outlined,
                  onPressed: () => ack('confirmed'),
                ),
              ]),
          ],
        );
      },
    );
  }
}

/// Assigned contractor: general access, and audited credentials when authorised.
class _AccessPanel extends ConsumerStatefulWidget {
  const _AccessPanel({required this.job});

  final ServiceJob job;

  @override
  ConsumerState<_AccessPanel> createState() => _AccessPanelState();
}

class _AccessPanelState extends ConsumerState<_AccessPanel> {
  bool _reveal = false;

  @override
  Widget build(BuildContext context) {
    final job = widget.job;
    final v = job.viewer;
    if (!v.can('access_general') && !v.can('access_restricted')) return const SizedBox.shrink();
    return SectionCard(
      title: 'Access and logistics',
      children: [
        if (v.can('access_general'))
          AsyncSection<AccessDetails>(
            value: ref.watch(accessGeneralProvider(job.id)),
            onRetry: () => ref.invalidate(accessGeneralProvider(job.id)),
            builder: (d) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final e in accessGeneralFields.entries)
                if ((d.values[e.key] ?? '').isNotEmpty) FactRow(e.value, d.values[e.key]!),
              if (d.values.values.every((x) => x == null || x.isEmpty)) const Text('No access notes yet.'),
            ]),
          ),
        if (v.can('access_restricted')) ...[
          const Divider(),
          if (!v.restrictedAccess)
            const Text('Access credentials are shared with your organisation, but the owner has not authorised you '
                'to see them.')
          else if (!_reveal)
            ActionButton(
              label: 'Show access credentials',
              icon: Icons.lock_open,
              onPressed: () => setState(() => _reveal = true),
            )
          else
            AsyncSection<AccessDetails>(
              value: ref.watch(accessRestrictedProvider(job.id)),
              onRetry: () => ref.invalidate(accessRestrictedProvider(job.id)),
              builder: (d) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Your viewing is recorded. Do not copy these into notes or messages.',
                    style: TextStyle(fontStyle: FontStyle.italic)),
                for (final e in accessRestrictedFields.entries)
                  if ((d.values[e.key] ?? '').isNotEmpty) FactRow(e.value, d.values[e.key]!),
              ]),
            ),
        ],
      ],
    );
  }
}

/// Renders a brief snapshot (escaped plain text only; never HTML).
class BriefContentView extends StatelessWidget {
  const BriefContentView({super.key, required this.content});

  final Map<String, dynamic> content;

  Map<String, dynamic>? _m(String k) => content[k] is Map ? (content[k] as Map).cast<String, dynamic>() : null;
  static List<Map<String, dynamic>> _l(Object? v) =>
      v is List ? [for (final e in v) if (e is Map) e.cast<String, dynamic>()] : const [];
  static String? _s(Map<String, dynamic> m, String k) => m[k] == null || '${m[k]}'.isEmpty ? null : '${m[k]}';

  Widget _heading(String text) => Padding(
        padding: const EdgeInsets.only(top: 12, bottom: 4),
        child: Semantics(header: true, child: Text(text, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15))),
      );

  @override
  Widget build(BuildContext context) {
    final summary = _m('summary');
    final evidence = _m('evidence');
    final access = _m('access_general');
    final measurements = _m('measurements');
    final preparation = _m('preparation');
    final scope = _m('scope');
    final limitations = content['limitations'] is List ? [for (final l in content['limitations'] as List) '$l'] : <String>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (summary != null) ...[
        _heading('The problem (as described by the owner)'),
        if (_s(summary, 'issue_description') != null) FactRow('What is happening', _s(summary, 'issue_description')!),
        if (_s(summary, 'affected_equipment') != null) FactRow('Equipment', _s(summary, 'affected_equipment')!),
        if (_s(summary, 'affected_system') != null) FactRow('System', _s(summary, 'affected_system')!),
        if (_s(summary, 'occurs_when') != null) FactRow('When', _s(summary, 'occurs_when')!),
        if (_s(summary, 'already_tried') != null) FactRow('Already tried', _s(summary, 'already_tried')!),
        if (_s(summary, 'urgency') != null) FactRow('Urgency', urgencyLabel(_s(summary, 'urgency'))),
        if (summary['vessel'] is Map) ...[
          Builder(builder: (_) {
            final v = (summary['vessel'] as Map).cast<String, dynamic>();
            final line = [v['make'], v['model'], v['year']].whereType<Object>().join(' ');
            final engine = [v['engine_make'], v['engine_model'], v['engine_year']].whereType<Object>().join(' ');
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              FactRow('Vessel (record)', line.isEmpty ? 'Unknown' : line),
              FactRow('Engine (record)', engine.isEmpty ? 'Unknown' : engine),
            ]);
          }),
        ],
      ],
      if (evidence != null) ...[
        _heading('Evidence'),
        Text('${_l(evidence['assets']).length} photo(s) or document(s) · '
            '${_l(evidence['observations']).length} observation(s) · ${_l(evidence['requests']).length} request(s)'),
        if (_l(evidence['gaps']).isNotEmpty) ...[
          const SizedBox(height: 4),
          const Text('Gaps and open requests:', style: TextStyle(fontWeight: FontWeight.w600)),
          for (final g in _l(evidence['gaps']))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text('• ${g['prompt']} — ${requestStatusLabel(g['status'] as String?)}'
                  '${g['unavailable_reason'] == null ? '' : ' (${unavailableReasonLabel(g['unavailable_reason'] as String?)})'}'
                  '${g['technician_inspection_required'] == true ? ' · inspect on site' : ''}'),
            ),
        ],
      ],
      if (access != null) ...[
        _heading('Access and logistics'),
        for (final e in accessGeneralFields.entries)
          if (_s(access, e.key) != null) FactRow(e.value, _s(access, e.key)!),
      ],
      if (measurements != null) ...[
        _heading('Measurements'),
        for (final m in _l(measurements['current']))
          Text('• ${m['component']} — ${dimensionLabel(m['dimension'] as String?)}: ${m['value_text']}'
              '${m['unit'] == null ? '' : ' ${m['unit']}'} (${provenanceLabel((m['provenance'] as Map?)?['badge'] as String?)})'),
        if (_l(measurements['current']).isEmpty) const Text('None recorded.'),
      ],
      if (preparation != null) ...[
        _heading('Preparation (provisional)'),
        for (final i in _l(preparation['items']))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text('• ${i['name']} — ${itemStatusLabel(i['status'] as String?)}'
                '${(i['open_requirements'] as List?)?.isNotEmpty == true ? '. Unknown: ${(i['open_requirements'] as List).join('; ')}' : ''}'),
          ),
        if (_l(preparation['needs_site_inspection']).isNotEmpty) ...[
          const Text('Needs site inspection:', style: TextStyle(fontWeight: FontWeight.w600)),
          for (final s in _l(preparation['needs_site_inspection'])) Text('• ${s['item'] ?? ''}: ${s['requirement']}'),
        ],
      ],
      if (scope != null) ...[
        _heading('Scope'),
        if (scope['current'] is Map)
          Builder(builder: (_) {
            final c = (scope['current'] as Map).cast<String, dynamic>();
            final total = c['estimate_total_minor'];
            return Text('Revision ${c['revision_number']}: ${c['summary']} — ${scopeStatusLabel(c['status'] as String?)}'
                '${total is int ? ' · estimate ${formatCents(total, currency: (c['currency'] as String?) ?? 'NZD')}' : ''}');
          })
        else
          const Text('No scope proposed yet.'),
      ],
      if (limitations.isNotEmpty) ...[
        _heading('Limitations'),
        BulletList(limitations),
      ],
      if (content.isEmpty) const Text('Nothing to show.', style: TextStyle(color: HelmTheme.mutedText)),
    ]);
  }
}
