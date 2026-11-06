import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';
import 'package:helm_marine/features/service_jobs/widgets/evidence_widgets.dart';

/// The owner's guided capture workspace: the next useful request with its
/// reason, safe alternatives, progress, gaps, uploads and observations.
class CaptureTab extends ConsumerWidget {
  const CaptureTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (job.isClosed) InfoNote('This job is ${jobStatusLabel(job.status).toLowerCase()}; evidence is read-only.'),
        AnalysisPanel(job: job),
        if (!job.isClosed) _NextStepCard(job: job),
        UploadProgressList(jobId: job.id),
        if (!job.isClosed)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              ActionButton(
                label: 'Take an extra photo',
                icon: Icons.photo_camera_outlined,
                onPressed: () => pickAndUpload(context, ref, job.id, camera: true),
              ),
              ActionButton(
                label: 'Upload an extra photo',
                icon: Icons.upload_file,
                onPressed: () => pickAndUpload(context, ref, job.id, camera: false),
              ),
            ]),
          ),
        _RequestsSection(job: job),
        AssetsSection(job: job),
        ObservationsSection(job: job),
      ],
    );
  }
}

/// Turns the current proposal into a request (if needed) and returns it.
Future<EvidenceRequest?> _ensureRequest(BuildContext context, WidgetRef ref, ServiceJob job, NextEvidence next) async {
  if (next.request != null) return next.request;
  final accepted = await runJobAction(
      context, ref, job.id, () => ref.read(serviceJobsApiProvider).acceptNext(job.id, key: next.proposal?.key));
  return accepted?.request;
}

List<Widget> requestActions(BuildContext context, WidgetRef ref, ServiceJob job,
    Future<EvidenceRequest?> Function() resolve, {bool allowWaive = true}) {
  final api = ref.read(serviceJobsApiProvider);
  return [
    ActionButton(
      label: 'Take photo',
      icon: Icons.photo_camera,
      filled: true,
      onPressed: () async {
        final r = await resolve();
        if (r != null && context.mounted) await pickAndUpload(context, ref, job.id, requestId: r.id, camera: true);
      },
    ),
    ActionButton(
      label: 'Upload a file',
      icon: Icons.upload_file,
      onPressed: () async {
        final r = await resolve();
        if (r != null && context.mounted) await pickAndUpload(context, ref, job.id, requestId: r.id, camera: false);
      },
    ),
    ActionButton(
      label: 'Answer with a note',
      icon: Icons.edit_note,
      onPressed: () async {
        final note = await promptText(context,
            title: 'Answer with a note',
            label: 'Your answer',
            message: 'Type what you can see or know — for example a marking or a model number.',
            confirm: 'Save answer',
            maxLength: 4000);
        if (note == null || !context.mounted) return;
        final r = await resolve();
        if (r == null || !context.mounted) return;
        await runJobAction(context, ref, job.id, () => api.answerRequest(job.id, r.id, note, expectedVersion: r.version),
            success: 'Answer saved');
      },
    ),
    ActionButton(
      label: 'I cannot safely get this',
      icon: Icons.do_not_touch_outlined,
      onPressed: () async {
        final gap = await showDialog<(String, String)>(context: context, builder: (_) => const _GapDialog());
        if (gap == null || !context.mounted) return;
        final r = await resolve();
        if (r == null || !context.mounted) return;
        await runJobAction(
            context, ref, job.id, () => api.markUnavailable(job.id, r.id, gap.$1, note: gap.$2, expectedVersion: r.version),
            success: 'Gap recorded — the contractor will see it');
      },
    ),
    if (allowWaive)
      ActionButton(
        label: 'Not needed',
        icon: Icons.remove_done,
        onPressed: () async {
          final r = await resolve();
          if (r == null || !context.mounted) return;
          await runJobAction(context, ref, job.id, () => api.waive(job.id, r.id, expectedVersion: r.version),
              success: 'Marked as no longer needed');
        },
      ),
  ];
}

class _NextStepCard extends ConsumerWidget {
  const _NextStepCard({required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final next = ref.watch(nextEvidenceProvider(job.id));
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: HelmTheme.primary, width: 1.5),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: AsyncSection<NextEvidence>(
          value: next,
          onRetry: () => ref.invalidate(nextEvidenceProvider(job.id)),
          builder: (n) {
            if (n.complete || (n.request == null && n.proposal == null)) {
              return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Semantics(
                  header: true,
                  container: true,
                  child: const Text('Nothing more is needed right now',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                ),
                const SizedBox(height: 8),
                Text(n.message),
                if (n.gaps.isNotEmpty) Text('${n.gaps.length} gap${n.gaps.length == 1 ? '' : 's'} will be shown in the brief.'),
              ]);
            }
            final r = n.request;
            final p = n.proposal;
            final prompt = r?.prompt ?? p!.prompt;
            final reason = r?.reason ?? p!.reason;
            final category = r?.category ?? p!.category;
            final fromContractor = r?.requesterRole == 'contractor';
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Wrap(spacing: 6, runSpacing: 6, children: [
                const StatusBadge('Next suggested request', tone: Tone.info, icon: Icons.lightbulb_outline),
                StatusBadge(evidenceCategoryLabel(category)),
                if (fromContractor) const StatusBadge('Requested by your contractor', tone: Tone.warn),
              ]),
              const SizedBox(height: 12),
              Semantics(
                header: true,
                container: true,
                child: Text(prompt, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              ),
              const SizedBox(height: 8),
              Text('Why this helps: $reason'),
              if (p != null) ...[
                const SizedBox(height: 8),
                InfoNote(p.safetyNote, tone: Tone.warn, icon: Icons.health_and_safety_outlined),
              ],
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: requestActions(context, ref, job, () => _ensureRequest(context, ref, job, n),
                    allowWaive: r != null),
              ),
            ]);
          },
        ),
      ),
    );
  }
}

class _GapDialog extends StatefulWidget {
  const _GapDialog();

  @override
  State<_GapDialog> createState() => _GapDialogState();
}

class _GapDialogState extends State<_GapDialog> {
  String _reason = 'cannot_safely_access';
  final _note = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('That is fine — leave it'),
      content: SizedBox(
        width: 420,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('We will record a gap. The contractor sees it in the brief and can check it on site. '
              'You can carry on with the rest.'),
          const SizedBox(height: 12),
          RadioGroup<String>(
            groupValue: _reason,
            onChanged: (v) => setState(() => _reason = v ?? _reason),
            child: Column(children: [
              for (final e in unavailableReasonLabels.entries)
                RadioListTile<String>(value: e.key, title: Text(e.value), contentPadding: EdgeInsets.zero),
            ]),
          ),
          TextField(
            controller: _note,
            maxLength: 2000,
            decoration: const InputDecoration(labelText: 'Anything the contractor should know? (optional)'),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(context, (_reason, _note.text)), child: const Text('Record gap')),
      ],
    );
  }
}

class _RequestsSection extends ConsumerWidget {
  const _RequestsSection({required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final requests = ref.watch(evidenceRequestsProvider(job.id));
    return SectionCard(
      title: 'Requests and gaps',
      subtitle: 'There is no fixed number of photos — answer what you safely can.',
      children: [
        AsyncSection<List<EvidenceRequest>>(
          value: requests,
          onRetry: () => ref.invalidate(evidenceRequestsProvider(job.id)),
          builder: (list) {
            if (list.isEmpty) return const Text('No requests yet. Start with the suggested request above.');
            final order = ['outstanding', 'unavailable', 'answered', 'waived'];
            final sorted = [...list]..sort((a, b) => order.indexOf(a.status).compareTo(order.indexOf(b.status)));
            return Column(children: [
              for (final r in sorted)
                RequestTile(
                  request: r,
                  actions: r.isOutstanding && !job.isClosed
                      ? requestActions(context, ref, job, () async => r)
                      : const [],
                ),
            ]);
          },
        ),
      ],
    );
  }
}
