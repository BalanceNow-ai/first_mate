import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Owner transitions this screen offers from each status (server enforces them).
const _ownerTransitions = <String, List<(String, String)>>{
  'draft': [('evidence_collection', 'Start collecting evidence')],
  'evidence_collection': [('contractor_review', 'Ready for contractor review')],
  'contractor_review': [('preparation_ready', 'Mark preparation ready'), ('evidence_collection', 'Back to evidence collection')],
  'preparation_ready': [('scheduled', 'Mark visit scheduled'), ('contractor_review', 'Back to contractor review')],
  'scheduled': [('preparation_ready', 'Back to preparation ready')],
};
const _preAttendance = {'draft', 'evidence_collection', 'contractor_review', 'preparation_ready', 'scheduled'};

/// Overview and resume: where the job is, what to do next, the vessel context.
class OverviewTab extends ConsumerWidget {
  const OverviewTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final next = ref.watch(nextEvidenceProvider(job.id));
    final ev = job.evidence;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          StatusBadge(jobStatusLabel(job.status), tone: jobStatusTone(job.status), semanticPrefix: 'Status'),
          StatusBadge('Urgency: ${urgencyLabel(job.urgency)}'),
          if (job.disputed) const StatusBadge('A record is disputed', tone: Tone.bad, icon: Icons.gavel),
          if (job.technicianInspectionRequired == true)
            const StatusBadge('Technician inspection needed', tone: Tone.warn, icon: Icons.engineering),
        ]),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Carry on where you left off',
          children: [
            AsyncSection<NextEvidence>(
              value: next,
              onRetry: () => ref.invalidate(nextEvidenceProvider(job.id)),
              builder: (n) {
                final text = n.request?.prompt ?? n.proposal?.prompt ?? n.message;
                return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(n.complete ? 'Nothing more is needed right now.' : 'Next suggested step:'),
                  const SizedBox(height: 4),
                  Text(text, style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (!n.complete) ...[
                    const SizedBox(height: 4),
                    Text('Why: ${n.request?.reason ?? n.proposal?.reason ?? n.message}'),
                  ],
                  const SizedBox(height: 12),
                  ActionButton(
                    label: 'Go to capture',
                    icon: Icons.photo_camera_outlined,
                    filled: true,
                    onPressed: () => GoRouter.of(context).go('/service-jobs/${job.id}/capture'),
                  ),
                ]);
              },
            ),
          ],
        ),
        if (ev != null)
          SectionCard(
            title: 'Progress',
            subtitle: 'You can carry on with gaps — the brief shows them to the contractor.',
            children: [
              FactRow('Photos ready', '${ev.availableAssetCount}'),
              FactRow('Answered', '${ev.answered.length}'),
              FactRow('Still needed', '${ev.outstanding.length}'),
              FactRow('Gaps recorded', '${ev.unavailable.length}'),
              FactRow('No longer needed', '${ev.waived.length}'),
              if ((job.gaps ?? const []).isNotEmpty) ...[
                const SizedBox(height: 8),
                const Text('Gaps', style: TextStyle(fontWeight: FontWeight.bold)),
                for (final g in job.gaps!) _GapTile(gap: g),
              ],
            ],
          ),
        SectionCard(
          title: 'The problem',
          trailing: job.isClosed
              ? null
              : TextButton.icon(
                  onPressed: () => _editDetails(context, ref),
                  icon: const Icon(Icons.edit),
                  label: const Text('Edit'),
                ),
          children: [
            if ((job.issueDescription ?? '').isNotEmpty) FactRow('What is happening', job.issueDescription!),
            if (job.affectedEquipment != null) FactRow('Equipment', job.affectedEquipment!),
            if (job.affectedSystem != null) FactRow('System', job.affectedSystem!),
            if (job.occursWhen != null) FactRow('When', job.occursWhen!),
            if (job.alreadyTried != null) FactRow('Already tried', job.alreadyTried!),
            FactRow('Started', formatDateTime(job.createdAt)),
          ],
        ),
        if (job.vesselContext != null) _VesselContextCard(job: job),
        if (job.viewer.isOwner) _StatusActions(job: job),
      ],
    );
  }

  Future<void> _editDetails(BuildContext context, WidgetRef ref) async {
    final changes = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _EditJobDialog(job: job),
    );
    if (changes == null || changes.isEmpty || !context.mounted) return;
    await runJobAction(context, ref, job.id,
        () => ref.read(serviceJobsApiProvider).updateJob(job.id, job.version, changes),
        success: 'Job updated');
  }
}

class _GapTile extends StatelessWidget {
  const _GapTile({required this.gap});

  final EvidenceGap gap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.report_gmailerrorred, color: HelmTheme.warning),
      title: Text(gap.prompt),
      subtitle: Text([
        if (gap.reason != null) unavailableReasonLabel(gap.reason),
        if (gap.note != null) gap.note!,
        if (gap.technicianInspectionRequired) 'Contractor to inspect on site',
      ].join(' · ')),
    );
  }
}

class _VesselContextCard extends ConsumerWidget {
  const _VesselContextCard({required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ctx = job.vesselContext!;
    final owner = job.viewer.isOwner && !job.isClosed;
    return SectionCard(
      title: 'Vessel details used for this job',
      subtitle: ctx.ownerConfirmed
          ? 'You confirmed these details.'
          : 'Taken from your vessel record — please confirm or correct them.',
      children: [
        if (ctx.nickname != null) FactRow('Vessel', ctx.nickname!),
        FactRow('Make, model, year', ctx.vesselLine.isEmpty ? 'Unknown' : ctx.vesselLine),
        FactRow('Engine', ctx.engineLine ?? 'Unknown'),
        for (final e in ctx.equipment)
          FactRow(humanise('${e['category']}'), [e['make'], e['model'], e['year']].whereType<Object>().join(' ')),
        if (ctx.corrections.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              'Corrected ${ctx.corrections.length} time${ctx.corrections.length == 1 ? '' : 's'}'
              '${ctx.corrections.last['note'] == null ? '' : ' — “${ctx.corrections.last['note']}”'}',
              style: const TextStyle(color: HelmTheme.mutedText),
            ),
          ),
        if (owner) ...[
          const SizedBox(height: 12),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (!ctx.ownerConfirmed)
              ActionButton(
                label: 'These details are right',
                icon: Icons.check,
                onPressed: () => runJobAction(context, ref, job.id,
                    () => ref.read(serviceJobsApiProvider).correctVesselContext(job.id, job.version),
                    success: 'Vessel details confirmed'),
              ),
            ActionButton(
              label: 'Correct vessel details',
              icon: Icons.edit,
              onPressed: () => _correct(context, ref),
            ),
          ]),
        ],
      ],
    );
  }

  Future<void> _correct(BuildContext context, WidgetRef ref) async {
    final ctx = job.vesselContext!;
    final result = await showDialog<_ContextCorrection>(
      context: context,
      builder: (_) => _CorrectContextDialog(ctx: ctx),
    );
    if (result == null || !context.mounted) return;
    await runJobAction(
      context,
      ref,
      job.id,
      () => ref.read(serviceJobsApiProvider).correctVesselContext(job.id, job.version,
          vessel: result.vessel, engine: result.engine, note: result.note),
      success: 'Vessel details corrected',
    );
  }
}

class _ContextCorrection {
  const _ContextCorrection(this.vessel, this.engine, this.note);

  final Map<String, dynamic> vessel;
  final Map<String, dynamic> engine;
  final String? note;
}

class _CorrectContextDialog extends StatefulWidget {
  const _CorrectContextDialog({required this.ctx});

  final VesselContext ctx;

  @override
  State<_CorrectContextDialog> createState() => _CorrectContextDialogState();
}

class _CorrectContextDialogState extends State<_CorrectContextDialog> {
  final _form = GlobalKey<FormState>();
  late final _make = TextEditingController(text: widget.ctx.vessel['make'] as String?);
  late final _model = TextEditingController(text: widget.ctx.vessel['model'] as String?);
  late final _year = TextEditingController(text: widget.ctx.vessel['year']?.toString());
  late final _engineMake = TextEditingController(text: widget.ctx.engine?['make'] as String?);
  late final _engineModel = TextEditingController(text: widget.ctx.engine?['model'] as String?);
  late final _engineYear = TextEditingController(text: widget.ctx.engine?['year']?.toString());
  final _note = TextEditingController();

  String? _yearError(String? v) {
    if (v == null || v.trim().isEmpty) return null;
    final y = int.tryParse(v.trim());
    return y == null || y < 1900 || y > 2100 ? 'Enter a year between 1900 and 2100' : null;
  }

  String? _t(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
  int? _y(TextEditingController c) => int.tryParse(c.text.trim());

  @override
  Widget build(BuildContext context) {
    Widget field(TextEditingController c, String label, {bool year = false}) => TextFormField(
          controller: c,
          decoration: InputDecoration(labelText: label),
          keyboardType: year ? TextInputType.number : null,
          validator: year ? _yearError : null,
        );
    return AlertDialog(
      title: const Text('Correct vessel details'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Text('Corrections apply to this job only; your vessel record is not changed.'),
              field(_make, 'Vessel make'),
              field(_model, 'Vessel model'),
              field(_year, 'Vessel year', year: true),
              field(_engineMake, 'Engine make'),
              field(_engineModel, 'Engine model'),
              field(_engineYear, 'Engine year', year: true),
              TextFormField(controller: _note, maxLength: 500, decoration: const InputDecoration(labelText: 'Note (optional)')),
            ]),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (!_form.currentState!.validate()) return;
            Navigator.pop(
              context,
              _ContextCorrection(
                {'make': _t(_make), 'model': _t(_model), 'year': _y(_year)},
                {'make': _t(_engineMake), 'model': _t(_engineModel), 'year': _y(_engineYear)},
                _note.text,
              ),
            );
          },
          child: const Text('Save corrections'),
        ),
      ],
    );
  }
}

class _EditJobDialog extends StatefulWidget {
  const _EditJobDialog({required this.job});

  final ServiceJob job;

  @override
  State<_EditJobDialog> createState() => _EditJobDialogState();
}

class _EditJobDialogState extends State<_EditJobDialog> {
  final _form = GlobalKey<FormState>();
  late final _title = TextEditingController(text: widget.job.title);
  late final _issue = TextEditingController(text: widget.job.issueDescription);
  late final _equipment = TextEditingController(text: widget.job.affectedEquipment);
  late final _when = TextEditingController(text: widget.job.occursWhen);
  late final _tried = TextEditingController(text: widget.job.alreadyTried);
  late String _urgency = widget.job.urgency ?? 'unknown';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Edit the problem'),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextFormField(
                controller: _title,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'Short title *'),
                validator: (v) => v == null || v.trim().isEmpty ? 'Give the job a short title' : null,
              ),
              TextFormField(controller: _issue, maxLines: 3, maxLength: 4000, decoration: const InputDecoration(labelText: 'What is happening?')),
              TextFormField(controller: _equipment, maxLength: 200, decoration: const InputDecoration(labelText: 'Which equipment is affected?')),
              TextFormField(controller: _when, maxLength: 2000, decoration: const InputDecoration(labelText: 'When does it happen?')),
              TextFormField(controller: _tried, maxLength: 2000, decoration: const InputDecoration(labelText: 'What have you already tried?')),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _urgency,
                decoration: const InputDecoration(labelText: 'Urgency'),
                items: [for (final e in urgencyLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                onChanged: (v) => setState(() => _urgency = v ?? _urgency),
              ),
            ]),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (!_form.currentState!.validate()) return;
            final j = widget.job;
            String? t(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();
            final changes = <String, dynamic>{
              if (_title.text.trim() != j.title) 'title': _title.text.trim(),
              if (_issue.text.trim() != (j.issueDescription ?? '')) 'issue_description': _issue.text.trim(),
              if (t(_equipment) != j.affectedEquipment) 'affected_equipment': t(_equipment),
              if (t(_when) != j.occursWhen) 'occurs_when': t(_when),
              if (t(_tried) != j.alreadyTried) 'already_tried': t(_tried),
              if (_urgency != j.urgency) 'urgency': _urgency,
            };
            Navigator.pop(context, changes);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class _StatusActions extends ConsumerWidget {
  const _StatusActions({required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(serviceJobsApiProvider);
    final transitions = _ownerTransitions[job.status] ?? const [];
    final canDelete = job.status == 'draft' && job.assignment == null;
    return SectionCard(
      title: 'Job status',
      subtitle: '“Preparation ready” means there is enough to review — not that the diagnosis or parts are correct.',
      children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final (to, label) in transitions)
            ActionButton(
              label: label,
              onPressed: () => runJobAction(context, ref, job.id, () => api.transition(job.id, job.version, to),
                  success: 'Status updated'),
            ),
          if (_preAttendance.contains(job.status))
            ActionButton(
              label: 'Cancel this job',
              icon: Icons.cancel_outlined,
              tone: Tone.bad,
              onPressed: () async {
                final ok = await confirmAction(context,
                    title: 'Cancel this job?',
                    message: 'The contractor (if any) is told the job is cancelled. This cannot be undone.',
                    confirm: 'Cancel job',
                    destructive: true);
                if (ok && context.mounted) {
                  await runJobAction(context, ref, job.id, () => api.transition(job.id, job.version, 'cancelled'),
                      success: 'Job cancelled');
                }
              },
            ),
          if (job.status == 'completed' || job.status == 'cancelled')
            ActionButton(
              label: 'Archive',
              icon: Icons.archive_outlined,
              onPressed: () =>
                  runJobAction(context, ref, job.id, () => api.archive(job.id, job.version), success: 'Job archived'),
            ),
          if (canDelete)
            ActionButton(
              label: 'Delete draft',
              icon: Icons.delete_outline,
              tone: Tone.bad,
              onPressed: () async {
                final ok = await confirmAction(context,
                    title: 'Delete this draft?',
                    message: 'The draft and its private photos are deleted now. It was never shared.',
                    confirm: 'Delete',
                    destructive: true);
                if (!ok || !context.mounted) return;
                final done = await runJobAction(context, ref, job.id, () async {
                  await api.deleteJob(job.id);
                  return true;
                });
                if (done == true && context.mounted) GoRouter.of(context).go('/service-jobs');
              },
            ),
        ]),
      ],
    );
  }
}
