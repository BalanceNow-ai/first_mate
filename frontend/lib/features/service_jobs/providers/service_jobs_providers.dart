import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/service_jobs/data/media_picker.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';

/// The owner's service jobs, a page at a time ("Load more" reads the next page).
final serviceJobListProvider =
    AsyncNotifierProvider.autoDispose<ServiceJobListController, Paged<JobListItem>>(ServiceJobListController.new);

class ServiceJobListController extends PagedNotifier<JobListItem> {
  @override
  String get listName => 'jobs';

  @override
  Future<Paged<JobListItem>> build() {
    requireUserId(ref);
    ref.watch(serviceJobsApiProvider);
    return super.build();
  }

  @override
  Future<List<JobListItem>> fetchPage({required int offset, required int limit}) =>
      ref.read(serviceJobsApiProvider).listJobs(limit: limit, offset: offset);
}

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
    required this.idempotencyKey,
    this.purpose = 'job_photo',
    this.requestId,
    this.caption,
    this.contentType,
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
  final String? caption;
  final String? contentType;
  final UploadStage stage;
  final ServiceAsset? asset;
  final Object? error;

  /// One key for this person's upload action: reused when the intent is retried, so
  /// a retry never creates a second asset; replaced only when the intent expired.
  final String idempotencyKey;

  /// Kept until the server has the content, so a failed PUT can be retried.
  final Uint8List? bytes;
  final String? uploadUrl;

  UploadTask copyWith({
    UploadStage? stage,
    ServiceAsset? asset,
    Object? error,
    String? uploadUrl,
    String? idempotencyKey,
    bool dropBytes = false,
    bool resetIntent = false,
  }) =>
      UploadTask(
        localId: localId,
        name: name,
        purpose: purpose,
        requestId: requestId,
        caption: caption,
        contentType: contentType,
        idempotencyKey: idempotencyKey ?? this.idempotencyKey,
        stage: stage ?? this.stage,
        asset: resetIntent ? null : (asset ?? this.asset),
        error: error,
        bytes: dropBytes ? null : bytes,
        uploadUrl: resetIntent ? null : (uploadUrl ?? this.uploadUrl),
      );
}

/// The intent's upload link has expired: a PUT to it can never succeed.
bool isUploadIntentExpired(Object? error) {
  final api = error == null ? null : ApiError.from(error);
  return api != null && (api.code == 'upload_intent_expired' || api.statusCode == 410);
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

  void _add(UploadTask task) {
    if (!ref.mounted) return;
    state = [...state, task];
  }

  void dismiss(String localId) => state = [for (final t in state) if (t.localId != localId) t];

  /// Uploads [media] (optionally answering [requestId]); returns the final asset.
  Future<ServiceAsset?> upload(PickedMedia media,
      {String? requestId, String? caption, String purpose = 'job_photo'}) {
    final task = UploadTask(
      localId: 'u${_seq++}',
      name: media.name,
      purpose: purpose,
      requestId: requestId,
      caption: caption,
      contentType: media.mimeType,
      idempotencyKey: newIdempotencyKey('upload'),
      stage: UploadStage.uploading,
      bytes: media.bytes,
    );
    _add(task);
    return _begin(task);
  }

  /// Creates (or, with the same key, re-reads) the intent, then sends the bytes.
  Future<ServiceAsset?> _begin(UploadTask task, {bool mayRestart = true}) async {
    _put(task);
    try {
      final intent = await _api.createAssetIntent(
        jobId,
        idempotencyKey: task.idempotencyKey,
        purpose: task.purpose,
        evidenceRequestId: task.requestId,
        caption: task.caption,
        filename: task.name,
        contentType: task.contentType,
        sizeBytes: task.bytes!.length,
      );
      final url = intent.upload?.url ?? _api.contentUrlFor(intent.asset.id);
      return await _send(task.copyWith(asset: intent.asset, uploadUrl: url), mayRestart: mayRestart);
    } catch (e) {
      _put(task.copyWith(stage: UploadStage.failed, error: e));
      return null;
    }
  }

  /// Abandons an expired intent (best effort) and starts a fresh one with a new key.
  Future<ServiceAsset?> _restart(UploadTask task) async {
    final old = task.asset;
    if (old != null) {
      try {
        await _api.deleteAsset(old.id, expectedVersion: old.version);
      } catch (_) {
        // The server also sweeps abandoned intents; a fresh upload must not wait on it.
      }
    }
    return _begin(
        task.copyWith(stage: UploadStage.uploading, idempotencyKey: newIdempotencyKey('upload'), resetIntent: true),
        mayRestart: false);
  }

  /// Retries a failed upload with the bytes still held: the intent with the same key,
  /// the PUT to the same link — or, if that link expired, a fresh intent.
  Future<ServiceAsset?> retry(String localId) async {
    final task = state.where((t) => t.localId == localId).firstOrNull;
    if (task == null || task.bytes == null) return null;
    final again = task.copyWith(stage: UploadStage.uploading);
    if (task.uploadUrl == null) return _begin(again);
    if (isUploadIntentExpired(task.error)) return _restart(again);
    return _send(again);
  }

  /// Resumes an interrupted upload (intent created, bytes never received). An intent
  /// whose link has expired is abandoned and a fresh one is started instead.
  Future<ServiceAsset?> resume(ServiceAsset asset, PickedMedia media) {
    final task = UploadTask(
      localId: 'u${_seq++}',
      name: media.name,
      purpose: asset.purpose,
      requestId: asset.evidenceRequestId,
      caption: asset.caption,
      contentType: media.mimeType,
      idempotencyKey: newIdempotencyKey('upload'),
      stage: UploadStage.uploading,
      asset: asset,
      bytes: media.bytes,
      uploadUrl: _api.contentUrlFor(asset.id),
    );
    _add(task);
    final expires = asset.uploadExpiresAt;
    if (expires != null && !expires.isAfter(DateTime.now())) return _restart(task);
    return _send(task);
  }

  Future<ServiceAsset?> _send(UploadTask task, {bool mayRestart = true}) async {
    _put(task);
    ServiceAsset asset;
    try {
      asset = await _api.putAssetContent(task.uploadUrl!, task.bytes!);
    } catch (e) {
      // The link expired while the person was away: never re-PUT to it.
      if (mayRestart && isUploadIntentExpired(e)) return _restart(task);
      _put(task.copyWith(stage: UploadStage.failed, error: e));
      return null;
    }
    try {
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
