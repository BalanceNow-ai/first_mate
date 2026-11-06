import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/service_jobs/data/media_picker.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';

/// The owner's service jobs.
final serviceJobListProvider = FutureProvider.autoDispose<List<JobListItem>>((ref) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).listJobs();
});

/// One job, filtered by the server to what the caller may see.
final serviceJobProvider = FutureProvider.autoDispose.family<ServiceJob, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).getJob(id);
});

final nextEvidenceProvider = FutureProvider.autoDispose.family<NextEvidence, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).nextEvidence(id);
});

final evidenceRequestsProvider = FutureProvider.autoDispose.family<List<EvidenceRequest>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).evidenceRequests(id);
});

final jobAssetsProvider = FutureProvider.autoDispose.family<AssetList, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).assets(id);
});

final analysisStatusProvider = FutureProvider.autoDispose.family<AnalysisStatus, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).analysisStatus(id);
});

final observationsProvider = FutureProvider.autoDispose.family<List<Observation>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).observations(id);
});

final measurementsProvider = FutureProvider.autoDispose.family<List<Measurement>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).measurements(id);
});

final preparationItemsProvider = FutureProvider.autoDispose.family<List<PreparationItem>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).preparationItems(id);
});

final accessGeneralProvider = FutureProvider.autoDispose.family<AccessDetails, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).accessGeneral(id);
});

/// Audited read: only fetched when the person asks to see it.
final accessRestrictedProvider = FutureProvider.autoDispose.family<AccessDetails, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).accessRestricted(id);
});

final assignmentsProvider = FutureProvider.autoDispose.family<List<Assignment>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).assignments(id);
});

final briefsProvider = FutureProvider.autoDispose.family<List<Brief>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).briefs(id);
});

final briefDetailProvider =
    FutureProvider.autoDispose.family<Brief, ({String jobId, String briefId})>((ref, key) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).brief(key.jobId, key.briefId);
});

final scopesProvider = FutureProvider.autoDispose.family<List<ScopeRevision>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).scopes(id);
});

final visitsProvider = FutureProvider.autoDispose.family<List<VisitEvent>, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).visits(id);
});

final feedbackProvider = FutureProvider.autoDispose.family<FeedbackOverview, String>((ref, id) {
  requireUserId(ref);
  return ref.watch(serviceJobsApiProvider).feedback(id);
});

/// Re-reads everything about a job after any mutation (versions and dependent
/// confirmations change together on the server).
void refreshServiceJob(WidgetRef ref, String id) {
  ref.invalidate(serviceJobProvider(id));
  ref.invalidate(nextEvidenceProvider(id));
  ref.invalidate(evidenceRequestsProvider(id));
  ref.invalidate(jobAssetsProvider(id));
  ref.invalidate(analysisStatusProvider(id));
  ref.invalidate(observationsProvider(id));
  ref.invalidate(measurementsProvider(id));
  ref.invalidate(preparationItemsProvider(id));
  ref.invalidate(accessGeneralProvider(id));
  ref.invalidate(assignmentsProvider(id));
  ref.invalidate(briefsProvider(id));
  ref.invalidate(scopesProvider(id));
  ref.invalidate(visitsProvider(id));
  ref.invalidate(feedbackProvider(id));
  ref.invalidate(serviceJobListProvider);
}

// ============================================================== uploads
enum UploadStage { uploading, checking, done, failed }

/// One upload in this session: intent → PUT bytes → poll until processed.
class UploadTask {
  const UploadTask({
    required this.localId,
    required this.name,
    required this.stage,
    this.purpose = 'job_photo',
    this.requestId,
    this.asset,
    this.error,
    this.bytes,
    this.uploadUrl,
  });

  final String localId;
  final String name;

  /// `job_photo` or `job_document`.
  final String purpose;
  final String? requestId;
  final UploadStage stage;
  final ServiceAsset? asset;
  final Object? error;

  /// Kept until the server has the content, so a failed PUT can be retried.
  final Uint8List? bytes;
  final String? uploadUrl;

  UploadTask copyWith({UploadStage? stage, ServiceAsset? asset, Object? error, String? uploadUrl, bool dropBytes = false}) =>
      UploadTask(
        localId: localId,
        name: name,
        purpose: purpose,
        requestId: requestId,
        stage: stage ?? this.stage,
        asset: asset ?? this.asset,
        error: error,
        bytes: dropBytes ? null : bytes,
        uploadUrl: uploadUrl ?? this.uploadUrl,
      );
}

/// How often an upload's processing status is re-read (tests override it).
final uploadPollIntervalProvider = Provider<Duration>((ref) => const Duration(seconds: 1));

final uploadsProvider =
    NotifierProvider.family<UploadsController, List<UploadTask>, String>(UploadsController.new);

class UploadsController extends Notifier<List<UploadTask>> {
  UploadsController(this.jobId);

  final String jobId;
  int _seq = 0;

  ServiceJobsApi get _api => ref.read(serviceJobsApiProvider);

  @override
  List<UploadTask> build() {
    ref.watch(serviceJobsApiProvider);
    return const [];
  }

  void _put(UploadTask task) {
    if (!ref.mounted) return;
    state = [for (final t in state) if (t.localId == task.localId) task else t];
  }

  void dismiss(String localId) => state = [for (final t in state) if (t.localId != localId) t];

  /// Uploads [media] (optionally answering [requestId]); returns the final asset.
  Future<ServiceAsset?> upload(PickedMedia media,
      {String? requestId, String? caption, String purpose = 'job_photo'}) async {
    final task = UploadTask(
      localId: 'u${_seq++}',
      name: media.name,
      purpose: purpose,
      requestId: requestId,
      stage: UploadStage.uploading,
      bytes: media.bytes,
    );
    state = [...state, task];
    try {
      final intent = await _api.createAssetIntent(
        jobId,
        idempotencyKey: newIdempotencyKey('upload'),
        purpose: purpose,
        evidenceRequestId: requestId,
        caption: caption,
        filename: media.name,
        contentType: media.mimeType,
        sizeBytes: media.bytes.length,
      );
      final url = intent.upload?.url ?? _api.contentUrlFor(intent.asset.id);
      return await _send(task.copyWith(asset: intent.asset, uploadUrl: url));
    } catch (e) {
      _put(task.copyWith(stage: UploadStage.failed, error: e));
      return null;
    }
  }

  /// Retries the PUT of a failed upload with the bytes still held.
  Future<ServiceAsset?> retry(String localId) async {
    final task = state.where((t) => t.localId == localId).firstOrNull;
    if (task == null || task.bytes == null) return null;
    if (task.uploadUrl == null) {
      dismiss(localId);
      return upload(PickedMedia(bytes: task.bytes!, name: task.name), requestId: task.requestId, purpose: task.purpose);
    }
    return _send(task.copyWith(stage: UploadStage.uploading));
  }

  /// Resumes an interrupted upload (intent created, bytes never received).
  Future<ServiceAsset?> resume(ServiceAsset asset, PickedMedia media) {
    final task = UploadTask(
      localId: 'u${_seq++}',
      name: media.name,
      purpose: asset.purpose,
      requestId: asset.evidenceRequestId,
      stage: UploadStage.uploading,
      asset: asset,
      bytes: media.bytes,
      uploadUrl: _api.contentUrlFor(asset.id),
    );
    state = [...state, task];
    return _send(task);
  }

  Future<ServiceAsset?> _send(UploadTask task) async {
    _put(task);
    try {
      var asset = await _api.putAssetContent(task.uploadUrl!, task.bytes!);
      var current = task.copyWith(stage: UploadStage.checking, asset: asset, dropBytes: true);
      _put(current);
      final interval = ref.read(uploadPollIntervalProvider);
      for (var i = 0; i < 120 && asset.inProgress; i++) {
        await Future<void>.delayed(interval);
        if (!ref.mounted) return asset;
        asset = await _api.asset(asset.id);
        current = current.copyWith(asset: asset);
        _put(current);
      }
      _put(current.copyWith(stage: asset.inProgress ? UploadStage.checking : UploadStage.done));
      return asset;
    } catch (e) {
      _put(task.copyWith(stage: UploadStage.failed, error: e));
      return null;
    }
  }
}
