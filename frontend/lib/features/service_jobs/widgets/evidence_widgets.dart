import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/media_picker.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Picks a photo (camera or file chooser) and uploads it through intent → PUT →
/// processing, answering [requestId] when given. Refreshes the job afterwards.
Future<ServiceAsset?> pickAndUpload(BuildContext context, WidgetRef ref, String jobId,
    {String? requestId, required bool camera}) async {
  PickedMedia? media;
  try {
    media = await ref.read(mediaPickerProvider).pick(camera: camera);
  } catch (e) {
    if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not open the photo');
    return null;
  }
  if (media == null) return null;
  final asset = await ref.read(uploadsProvider(jobId).notifier).upload(media, requestId: requestId);
  refreshServiceJob(ref, jobId);
  if (context.mounted && asset != null) {
    final msg = switch (asset.status) {
      'available' => 'Photo added',
      'rejected' => 'Photo rejected: ${rejectionReasonLabel(asset.rejectionReason)}',
      _ => 'Photo received — still being checked',
    };
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }
  return asset;
}

/// Opens a short-lived signed download link in a new tab (never shows storage paths).
Future<void> openDownload(BuildContext context, WidgetRef ref, ServiceAsset asset) async {
  try {
    final api = ref.read(serviceJobsApiProvider);
    final link = await api.downloadUrl(asset.id);
    await ref.read(urlOpenerProvider)(api.resolve(link.url));
  } catch (e) {
    if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not open the download');
  }
}

/// Uploads in progress during this session (with retry after a failure).
class UploadProgressList extends ConsumerWidget {
  const UploadProgressList({super.key, required this.jobId});

  final String jobId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(uploadsProvider(jobId));
    if (tasks.isEmpty) return const SizedBox.shrink();
    final controller = ref.read(uploadsProvider(jobId).notifier);
    return SectionCard(
      title: 'Uploads',
      children: [
        for (final t in tasks)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: switch (t.stage) {
              UploadStage.uploading || UploadStage.checking => const SizedBox(
                  width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2.5, semanticsLabel: 'Uploading')),
              UploadStage.done => Icon(
                  t.asset?.isAvailable == true ? Icons.check_circle : Icons.error_outline,
                  color: t.asset?.isAvailable == true ? HelmTheme.success : HelmTheme.error,
                ),
              UploadStage.failed => const Icon(Icons.error_outline, color: HelmTheme.error),
            },
            title: Text(t.name),
            subtitle: Text(switch (t.stage) {
              UploadStage.uploading => 'Uploading…',
              UploadStage.checking => '${assetStatusLabel(t.asset?.status)}…',
              UploadStage.done => t.asset?.status == 'rejected'
                  ? 'Rejected: ${rejectionReasonLabel(t.asset?.rejectionReason)}'
                  : assetStatusLabel(t.asset?.status),
              UploadStage.failed => 'Upload failed: ${t.error == null ? 'unknown error' : describeError(t.error!)}',
            }),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              if (t.stage == UploadStage.failed && t.bytes != null)
                TextButton(
                  onPressed: () async {
                    await controller.retry(t.localId);
                    refreshServiceJob(ref, jobId);
                  },
                  child: const Text('Retry upload'),
                ),
              if (t.stage == UploadStage.done || t.stage == UploadStage.failed)
                IconButton(
                  tooltip: 'Dismiss',
                  icon: const Icon(Icons.close),
                  onPressed: () => controller.dismiss(t.localId),
                ),
            ]),
          ),
      ],
    );
  }
}

/// Photos and documents for the job with status, quality hints and actions.
class AssetsSection extends ConsumerWidget {
  const AssetsSection({super.key, required this.job, this.title = 'Photos and documents'});

  final ServiceJob job;
  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assets = ref.watch(jobAssetsProvider(job.id));
    return SectionCard(
      title: title,
      subtitle: 'Photos show what is visible. They are not proof of a diagnosis, dimension or safety. '
          'Downloads open a short-lived private link.',
      children: [
        AsyncSection<AssetList>(
          value: assets,
          onRetry: () => ref.invalidate(jobAssetsProvider(job.id)),
          builder: (list) => list.items.isEmpty
              ? const Text('No photos yet.')
              : Column(children: [for (final a in list.items) AssetTile(job: job, asset: a)]),
        ),
      ],
    );
  }
}

class AssetTile extends ConsumerWidget {
  const AssetTile({super.key, required this.job, required this.asset});

  final ServiceJob job;
  final ServiceAsset asset;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final a = asset;
    final owner = job.viewer.isOwner;
    final tone = switch (a.status) {
      'available' => Tone.good,
      'rejected' => Tone.bad,
      _ => Tone.warn,
    };
    final hints = [
      if (a.isAvailable) for (final k in qualityKeys) if (a.quality.containsKey(k)) qualityHint(k, a.quality[k]),
      if (a.isAvailable && a.quality.isEmpty) 'Quality: not assessed',
    ];
    final meta = [
      if (a.detectedType != null) a.detectedType!,
      if (a.width != null && a.height != null) '${a.width}×${a.height}',
      if (a.sizeBytes != null) formatBytes(a.sizeBytes!),
      'Added ${formatDateTime(a.createdAt)} by ${a.uploadedByMe ? 'you' : a.uploadedByRole}',
    ];
    final retake = owner && (a.status == 'rejected' || (a.isAvailable && qualityNeedsRetake(a.quality)));
    final interrupted = owner && a.status == 'upload_pending' && a.uploadedByMe;
    return Card(
      color: HelmTheme.surface,
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(a.purpose == 'job_document' ? Icons.description_outlined : Icons.photo_outlined),
            const SizedBox(width: 8),
            Expanded(
              child: Text(a.caption ?? (a.purpose == 'job_document' ? 'Document' : 'Photo'),
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            StatusBadge(assetStatusLabel(a.status), tone: tone, semanticPrefix: 'Photo status'),
          ]),
          const SizedBox(height: 6),
          Text(meta.join(' · '), style: const TextStyle(color: HelmTheme.mutedText, fontSize: 13)),
          if (a.status == 'rejected') ...[
            const SizedBox(height: 6),
            Text(rejectionReasonLabel(a.rejectionReason), style: const TextStyle(color: HelmTheme.error)),
          ],
          if (a.inProgress && !interrupted) ...[
            const SizedBox(height: 6),
            const Text('Checked for safety before anyone can see it. This usually takes a few seconds.'),
          ],
          if (interrupted) ...[
            const SizedBox(height: 6),
            const Text('This upload was interrupted. Choose the same photo again to finish it.'),
          ],
          if (a.duplicateOfId != null) ...[
            const SizedBox(height: 6),
            const Text('Looks like a duplicate of another photo — it is not counted as extra evidence.'),
          ],
          if (hints.isNotEmpty) ...[
            const SizedBox(height: 6),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final h in hints)
                StatusBadge(h, tone: h.contains('OK') || h.contains('readable') ? Tone.good : Tone.neutral),
            ]),
          ],
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (a.isAvailable)
              ActionButton(
                label: 'Download',
                icon: Icons.download,
                onPressed: () => openDownload(context, ref, a),
              ),
            if (interrupted)
              ActionButton(
                label: 'Finish upload',
                icon: Icons.upload,
                onPressed: () async {
                  final media = await ref.read(mediaPickerProvider).pick(camera: false);
                  if (media == null) return;
                  await ref.read(uploadsProvider(job.id).notifier).resume(a, media);
                  refreshServiceJob(ref, job.id);
                },
              ),
            if (retake)
              ActionButton(
                label: 'Retake',
                icon: Icons.photo_camera,
                onPressed: () => pickAndUpload(context, ref, job.id, requestId: a.evidenceRequestId, camera: true),
              ),
            if (owner || (a.uploadedByMe && !a.isAvailable))
              ActionButton(
                label: 'Delete',
                icon: Icons.delete_outline,
                tone: Tone.bad,
                onPressed: () async {
                  final ok = await confirmAction(context,
                      title: 'Delete this photo?',
                      message: 'The file is removed from Helm. Copies someone already downloaded cannot be recalled.',
                      confirm: 'Delete',
                      destructive: true);
                  if (ok && context.mounted) {
                    await runJobAction(context, ref, job.id, () async {
                      await ref.read(serviceJobsApiProvider).deleteAsset(a.id, expectedVersion: a.version);
                      return true;
                    }, success: 'Photo deleted');
                  }
                },
              ),
          ]),
        ]),
      ),
    );
  }
}

/// Observations: what evidence appears to show — suggestions and notes, not measurements.
class ObservationsSection extends ConsumerWidget {
  const ObservationsSection({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final obs = ref.watch(observationsProvider(job.id));
    return SectionCard(
      title: 'Observations',
      subtitle: 'What the photos appear to show. Suggestions are not measurements or a diagnosis.',
      trailing: TextButton.icon(
        icon: const Icon(Icons.note_add_outlined),
        label: const Text('Add a note'),
        onPressed: () async {
          final text = await promptText(context, title: 'Add a note', label: 'Note', maxLength: 2000);
          if (text == null || !context.mounted) return;
          await runJobAction(context, ref, job.id,
              () => ref.read(serviceJobsApiProvider).addObservationNote(job.id, text),
              success: 'Note added');
        },
      ),
      children: [
        AsyncSection<List<Observation>>(
          value: obs,
          onRetry: () => ref.invalidate(observationsProvider(job.id)),
          builder: (list) {
            final active = list.where((o) => o.isActive).toList();
            final inactive = list.length - active.length;
            if (active.isEmpty) return const Text('No observations yet.');
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final o in active)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(o.assertion),
                  subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const SizedBox(height: 4),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      StatusBadge(originLabel(o.origin), tone: o.origin == 'model' ? Tone.warn : Tone.info),
                      ProvenanceBadge(o.state),
                    ]),
                    if (o.extractedText != null) Text('Text in the image appears to read: “${o.extractedText}”'),
                    if (o.uncertainty != null) Text(o.uncertainty!),
                  ]),
                  trailing: o.origin == 'model'
                      ? TextButton(
                          onPressed: () => runJobAction(context, ref, job.id,
                              () => ref.read(serviceJobsApiProvider).rejectObservation(job.id, o.id),
                              success: 'Suggestion rejected'),
                          child: const Text('Reject'),
                        )
                      : null,
                ),
              if (inactive > 0)
                Text('$inactive rejected or superseded observation${inactive == 1 ? '' : 's'} kept for the record.',
                    style: const TextStyle(color: HelmTheme.mutedText)),
            ]);
          },
        ),
      ],
    );
  }
}

/// Honest analysis availability: manual capture always keeps working.
class AnalysisPanel extends ConsumerWidget {
  const AnalysisPanel({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(analysisStatusProvider(job.id));
    return status.when(
      loading: () => const SizedBox.shrink(),
      error: (e, _) => const InfoNote(
        'Photo analysis status is unavailable right now. You can still add photos, notes and measurements.',
        tone: Tone.warn,
      ),
      data: (s) {
        if (!s.available) {
          return InfoNote(
            'Photo analysis is unavailable${s.message == null ? '' : ': ${s.message}'}. '
            'Everything else keeps working — add photos, notes and measurements yourself.',
            tone: Tone.warn,
            icon: Icons.cloud_off,
          );
        }
        final latest = s.runs.isEmpty ? null : s.runs.last;
        return SectionCard(
          title: 'Photo analysis',
          subtitle: s.substitute
              ? 'Local test analyser: it exercises the workflow, not real visual accuracy.'
              : 'Results are suggestions for you to check — never measurements or a diagnosis.',
          children: [
            if (latest != null)
              Text('Last run: ${humanise(latest.status)} · ${latest.observationCount} observation'
                  '${latest.observationCount == 1 ? '' : 's'}${latest.error == null ? '' : ' · ${latest.error}'}'),
            const SizedBox(height: 8),
            ActionButton(
              label: latest?.inProgress == true ? 'Analysing…' : 'Analyse photos',
              icon: Icons.auto_awesome_outlined,
              onPressed: latest?.inProgress == true
                  ? null
                  : () async {
                      final run = await runJobAction(context, ref, job.id,
                          () => ref.read(serviceJobsApiProvider).requestAnalysis(job.id,
                              idempotencyKey: newIdempotencyKey('analysis')),
                          success: 'Analysis queued');
                      if (run != null) {
                        await _waitFor(ref, job.id, run);
                      }
                    },
            ),
          ],
        );
      },
    );
  }

  Future<void> _waitFor(WidgetRef ref, String jobId, AnalysisRun run) async {
    final api = ref.read(serviceJobsApiProvider);
    final interval = ref.read(uploadPollIntervalProvider);
    var current = run;
    for (var i = 0; i < 60 && current.inProgress; i++) {
      await Future<void>.delayed(interval);
      try {
        current = await api.analysisRun(jobId, run.id);
      } catch (_) {
        break;
      }
    }
    refreshServiceJob(ref, jobId);
  }
}

/// One evidence request with its status, reason and (for the owner) actions.
class RequestTile extends StatelessWidget {
  const RequestTile({super.key, required this.request, this.actions = const []});

  final EvidenceRequest request;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final r = request;
    final tone = switch (r.status) {
      'answered' => Tone.good,
      'unavailable' => Tone.warn,
      'waived' => Tone.neutral,
      _ => Tone.info,
    };
    return Card(
      color: HelmTheme.surface,
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 6, runSpacing: 6, children: [
            StatusBadge(requestStatusLabel(r.status), tone: tone, semanticPrefix: 'Request'),
            StatusBadge(evidenceCategoryLabel(r.category)),
            StatusBadge(requesterLabel(r.requesterRole)),
            if (r.technicianInspectionRequired)
              const StatusBadge('Contractor to inspect on site', tone: Tone.warn, icon: Icons.engineering),
          ]),
          const SizedBox(height: 8),
          Text(r.prompt, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text('Why it helps: ${r.reason}'),
          if (r.unavailableReason != null) Text('Gap: ${unavailableReasonLabel(r.unavailableReason)}'),
          if (r.answerNote != null) Text('Note: ${r.answerNote}'),
          if (actions.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: actions),
          ],
        ]),
      ),
    );
  }
}

/// Shows a 403/404 failure as a plain message.
String accessMessage(Object e) {
  final api = ApiError.from(e);
  if (api?.statusCode == 403) return 'This part of the job has not been shared with you.';
  if (api?.statusCode == 404) return 'This job is not available to you.';
  return describeError(e);
}
