import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/files/file_saver.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';

/// Service-jobs API (`/service-jobs/*`, `/service-assets/*`, `/service-feedback/*`),
/// scoped to the signed-in user (a new client per user).
final serviceJobsApiProvider = Provider<ServiceJobsApi>((ref) {
  ref.watch(currentUserIdProvider);
  return ServiceJobsApi(ref.watch(dioProvider));
});

final _random = Random.secure();

/// A fresh per-action idempotency key (8–100 chars of `[A-Za-z0-9_-:.]`).
String newIdempotencyKey(String tag) {
  final hex = List.generate(16, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  return 'helm-$tag-$hex';
}

class ServiceJobsApi {
  ServiceJobsApi(this._dio);

  final Dio _dio;

  Future<T> _call<T>(Future<Response<dynamic>> Function() send, T Function(dynamic) parse) async {
    try {
      return parse((await send()).data);
    } on DioException catch (e) {
      throw ApiError.from(e)!;
    }
  }

  static Map<String, dynamic> _map(dynamic d) => (d as Map).cast<String, dynamic>();
  static List<T> _list<T>(dynamic d, T Function(Map<String, dynamic>) f) => [for (final e in d as List) f(_map(e))];
  static Options _idem(String key) => Options(headers: {'Idempotency-Key': key});

  String _job(String id) => '/service-jobs/$id';

  /// Resolves a server-relative URL (e.g. `/api/v1/service-assets/…/content`
  /// or a local signed download) against the API origin.
  Uri resolve(String url) => Uri.parse(_dio.options.baseUrl).resolve(url);

  // ------------------------------------------------------------------ jobs
  Future<List<JobListItem>> listJobs({String? status, bool includeArchived = false}) => _call(
        () => _dio.get('/service-jobs/', queryParameters: {
          'status': ?status,
          if (includeArchived) 'include_archived': true,
        }),
        (d) => _list(d, JobListItem.fromJson),
      );

  Future<ServiceJob> createJob(JobDraft draft) =>
      _call(() => _dio.post('/service-jobs/', data: draft.toJson()), (d) => ServiceJob.fromJson(_map(d)));

  Future<ServiceJob> getJob(String id) => _call(() => _dio.get(_job(id)), (d) => ServiceJob.fromJson(_map(d)));

  Future<ServiceJob> updateJob(String id, int expectedVersion, Map<String, dynamic> changes) => _call(
        () => _dio.patch(_job(id), data: {'expected_version': expectedVersion, ...changes}),
        (d) => ServiceJob.fromJson(_map(d)),
      );

  /// Confirms (no changes) or corrects the vessel/equipment snapshot.
  Future<ServiceJob> correctVesselContext(
    String id,
    int expectedVersion, {
    Map<String, dynamic>? vessel,
    Map<String, dynamic>? engine,
    String? note,
  }) =>
      _call(
        () => _dio.put('${_job(id)}/vessel-context', data: {
          'expected_version': expectedVersion,
          'vessel': ?vessel,
          'engine': ?engine,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => ServiceJob.fromJson(_map(d)),
      );

  Future<ServiceJob> transition(String id, int expectedVersion, String to, {String? note}) => _call(
        () => _dio.post('${_job(id)}/transition', data: {
          'expected_version': expectedVersion,
          'to': to,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => ServiceJob.fromJson(_map(d)),
      );

  Future<ServiceJob> archive(String id, int expectedVersion) => _call(
        () => _dio.post('${_job(id)}/archive', data: {'expected_version': expectedVersion}),
        (d) => ServiceJob.fromJson(_map(d)),
      );

  Future<void> deleteJob(String id) => _call(() => _dio.delete(_job(id)), (_) {});

  // ------------------------------------------------------------------ access details
  Future<AccessDetails> accessGeneral(String id) =>
      _call(() => _dio.get('${_job(id)}/access/general'), (d) => AccessDetails.fromJson(_map(d), 'general'));

  Future<AccessDetails> putAccessGeneral(String id, int expectedVersion, Map<String, String?> general) => _call(
        () => _dio.put('${_job(id)}/access/general', data: {'expected_version': expectedVersion, 'general': general}),
        (d) => AccessDetails.fromJson(_map(d), 'general'),
      );

  /// Audited: the owner, or an assigned member the owner authorised.
  Future<AccessDetails> accessRestricted(String id) =>
      _call(() => _dio.get('${_job(id)}/access/restricted'), (d) => AccessDetails.fromJson(_map(d), 'restricted'));

  Future<AccessDetails> putAccessRestricted(String id, int expectedVersion, Map<String, String?> restricted) => _call(
        () => _dio.put('${_job(id)}/access/restricted',
            data: {'expected_version': expectedVersion, 'restricted': restricted}),
        (d) => AccessDetails.fromJson(_map(d), 'restricted'),
      );

  // ------------------------------------------------------------------ assignments
  Future<List<Assignment>> assignments(String id) =>
      _call(() => _dio.get('${_job(id)}/assignments'), (d) => _list(d, Assignment.fromJson));

  Map<String, dynamic> _invite(String organizationId, List<String> sections, bool liveUpdates) =>
      {'organization_id': organizationId, 'sections': sections, 'live_updates': liveUpdates};

  Future<SharingPreview> previewSharing(String id, String organizationId, List<String> sections, bool liveUpdates) =>
      _call(
        () => _dio.post('${_job(id)}/assignments/preview', data: _invite(organizationId, sections, liveUpdates)),
        (d) => SharingPreview.fromJson(_map(d)),
      );

  Future<Assignment> invite(String id, String organizationId, List<String> sections, bool liveUpdates,
          {required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/assignments',
            data: _invite(organizationId, sections, liveUpdates), options: _idem(idempotencyKey)),
        (d) => Assignment.fromJson(_map(d)),
      );

  Future<Assignment> updateSharing(String id, String assignmentId, int expectedVersion,
          {List<String>? sections, bool? liveUpdates}) =>
      _call(
        () => _dio.patch('${_job(id)}/assignments/$assignmentId', data: {
          'expected_version': expectedVersion,
          'sections': ?sections,
          'live_updates': ?liveUpdates,
        }),
        (d) => Assignment.fromJson(_map(d)),
      );

  Future<Assignment> setMemberRestrictedAccess(
          String id, String assignmentId, String memberId, bool allowed, int expectedVersion) =>
      _call(
        () => _dio.put('${_job(id)}/assignments/$assignmentId/members/$memberId',
            data: {'restricted_access': allowed, 'expected_version': expectedVersion}),
        (d) => Assignment.fromJson(_map(d)),
      );

  Future<Assignment> revoke(String id, String assignmentId, {String? reason}) => _call(
        () => _dio.post('${_job(id)}/assignments/$assignmentId/revoke',
            data: {if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim()}),
        (d) => Assignment.fromJson(_map(d)),
      );

  Future<Assignment> reassign(String id, String assignmentId, String organizationId, List<String> sections,
          bool liveUpdates, {required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/assignments/$assignmentId/reassign',
            data: _invite(organizationId, sections, liveUpdates), options: _idem(idempotencyKey)),
        (d) => Assignment.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ evidence requests
  Future<NextEvidence> nextEvidence(String id) =>
      _call(() => _dio.get('${_job(id)}/evidence-requests/next'), (d) => NextEvidence.fromJson(_map(d)));

  /// Turns the current proposal into an outstanding request (or returns the existing one).
  Future<NextEvidence> acceptNext(String id, {String? key}) => _call(
        () => _dio.post('${_job(id)}/evidence-requests/next', queryParameters: {'key': ?key}),
        (d) => NextEvidence.fromJson(_map(d)),
      );

  Future<List<EvidenceRequest>> evidenceRequests(String id, {String? status}) => _call(
        () => _dio.get('${_job(id)}/evidence-requests', queryParameters: {'status': ?status}),
        (d) => _list(d, EvidenceRequest.fromJson),
      );

  Future<EvidenceRequest> createEvidenceRequest(String id,
          {required String category,
          required String prompt,
          required String reason,
          String? component,
          String? measurementDimension,
          String? priority}) =>
      _call(
        () => _dio.post('${_job(id)}/evidence-requests', data: {
          'category': category,
          'prompt': prompt.trim(),
          'reason': reason.trim(),
          if (component != null && component.trim().isNotEmpty) 'component': component.trim(),
          'measurement_dimension': ?measurementDimension,
          'priority': ?priority,
        }),
        (d) => EvidenceRequest.fromJson(_map(d)),
      );

  Future<EvidenceRequest> answerRequest(String id, String requestId, String note, {int? expectedVersion}) => _call(
        () => _dio.post('${_job(id)}/evidence-requests/$requestId/answer',
            data: {'note': note.trim(), 'expected_version': ?expectedVersion}),
        (d) => EvidenceRequest.fromJson(_map(d)),
      );

  Future<EvidenceRequest> markUnavailable(String id, String requestId, String reason,
          {String? note, int? expectedVersion}) =>
      _call(
        () => _dio.post('${_job(id)}/evidence-requests/$requestId/unavailable', data: {
          'reason': reason,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
          'expected_version': ?expectedVersion,
        }),
        (d) => EvidenceRequest.fromJson(_map(d)),
      );

  Future<EvidenceRequest> waive(String id, String requestId, {String? note, int? expectedVersion}) => _call(
        () => _dio.post('${_job(id)}/evidence-requests/$requestId/waive', data: {
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
          'expected_version': ?expectedVersion,
        }),
        (d) => EvidenceRequest.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ media
  Future<AssetIntent> createAssetIntent(String id,
          {required String idempotencyKey,
          String purpose = 'job_photo',
          String? evidenceRequestId,
          String? caption,
          String? filename,
          String? contentType,
          int? sizeBytes}) =>
      _call(
        () => _dio.post('${_job(id)}/assets/intents',
            data: {
              'purpose': purpose,
              'evidence_request_id': ?evidenceRequestId,
              if (caption != null && caption.trim().isNotEmpty) 'caption': caption.trim(),
              'filename': ?filename,
              'content_type': ?contentType,
              'size_bytes': ?sizeBytes,
            },
            options: _idem(idempotencyKey)),
        (d) => AssetIntent.fromJson(_map(d)),
      );

  /// PUTs the raw bytes to the intent's upload URL (the server checks the content itself).
  Future<ServiceAsset> putAssetContent(String uploadUrl, Uint8List bytes) => _call(
        () => _dio.putUri(resolve(uploadUrl),
            data: bytes,
            options: Options(contentType: 'application/octet-stream', sendTimeout: const Duration(minutes: 2))),
        (d) => ServiceAsset.fromJson(_map(d)),
      );

  /// The content URL of an asset whose upload was interrupted.
  String contentUrlFor(String assetId) => '/api/v1/service-assets/$assetId/content';

  Future<ServiceAsset> asset(String assetId) =>
      _call(() => _dio.get('/service-assets/$assetId'), (d) => ServiceAsset.fromJson(_map(d)));

  Future<AssetList> assets(String id) => _call(() => _dio.get('${_job(id)}/assets'), (d) => AssetList.fromJson(_map(d)));

  /// A short-lived attachment link (derivative unless the owner asks for the original).
  Future<DownloadLink> downloadUrl(String assetId, {String variant = 'derivative'}) => _call(
        () => _dio.post('/service-assets/$assetId/download-url', data: {'variant': variant}),
        (d) => DownloadLink.fromJson(_map(d)),
      );

  Future<void> deleteAsset(String assetId, {int? expectedVersion}) => _call(
        () => _dio.delete('/service-assets/$assetId', queryParameters: {'expected_version': ?expectedVersion}),
        (_) {},
      );

  // ------------------------------------------------------------------ analysis + observations
  Future<AnalysisStatus> analysisStatus(String id) =>
      _call(() => _dio.get('${_job(id)}/analysis'), (d) => AnalysisStatus.fromJson(_map(d)));

  Future<AnalysisRun> requestAnalysis(String id, {required String idempotencyKey, List<String>? assetIds}) => _call(
        () => _dio.post('${_job(id)}/analysis', data: {'asset_ids': ?assetIds}, options: _idem(idempotencyKey)),
        (d) => AnalysisRun.fromJson(_map(d)),
      );

  Future<AnalysisRun> analysisRun(String id, String runId) =>
      _call(() => _dio.get('${_job(id)}/analysis/$runId'), (d) => AnalysisRun.fromJson(_map(d)));

  Future<List<Observation>> observations(String id) =>
      _call(() => _dio.get('${_job(id)}/observations'), (d) => _list(d, Observation.fromJson));

  Future<Observation> addObservationNote(String id, String text, {String? assetId}) => _call(
        () => _dio.post('${_job(id)}/observations', data: {'text': text.trim(), 'asset_id': ?assetId}),
        (d) => Observation.fromJson(_map(d)),
      );

  Future<Observation> rejectObservation(String id, String observationId, {String? note}) => _call(
        () => _dio.post('${_job(id)}/observations/$observationId/reject',
            data: {if (note != null && note.trim().isNotEmpty) 'note': note.trim()}),
        (d) => Observation.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ measurements
  Future<List<Measurement>> measurements(String id) =>
      _call(() => _dio.get('${_job(id)}/measurements'), (d) => _list(d, Measurement.fromJson));

  Future<Measurement> recordMeasurement(String id, MeasurementInput input) => _call(
        () => _dio.post('${_job(id)}/measurements', data: input.toJson()),
        (d) => Measurement.fromJson(_map(d)),
      );

  Future<Measurement> reviseMeasurement(String id, String measurementId, MeasurementInput input) => _call(
        () => _dio.post('${_job(id)}/measurements/$measurementId/revise', data: input.toJson()),
        (d) => Measurement.fromJson(_map(d)),
      );

  Future<Measurement> confirmMeasurement(String id, String measurementId, String method, {String? note}) => _call(
        () => _dio.post('${_job(id)}/measurements/$measurementId/confirm', data: {
          'method': method,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => Measurement.fromJson(_map(d)),
      );

  Future<Measurement> rejectMeasurement(String id, String measurementId, {String? note}) => _call(
        () => _dio.post('${_job(id)}/measurements/$measurementId/reject',
            data: {if (note != null && note.trim().isNotEmpty) 'note': note.trim()}),
        (d) => Measurement.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ preparation
  Future<List<PreparationItem>> preparationItems(String id) =>
      _call(() => _dio.get('${_job(id)}/preparation-items'), (d) => _list(d, PreparationItem.fromJson));

  Future<List<PreparationItem>> suggestPreparation(String id) =>
      _call(() => _dio.post('${_job(id)}/preparation-items/suggest'), (d) => _list(d, PreparationItem.fromJson));

  Future<PreparationItem> createPreparationItem(String id, PreparationItemInput input) => _call(
        () => _dio.post('${_job(id)}/preparation-items', data: input.toJson()),
        (d) => PreparationItem.fromJson(_map(d)),
      );

  Future<PreparationItem> confirmItem(String id, PreparationItem item,
          {String? quantity, String? unit, String? quantityBasis, String? note}) =>
      _call(
        () => _dio.post('${_job(id)}/preparation-items/${item.id}/confirm', data: {
          'expected_version': item.version,
          if (quantity != null && quantity.trim().isNotEmpty) 'quantity': quantity.trim(),
          if (unit != null && unit.trim().isNotEmpty) 'unit': unit.trim(),
          if (quantityBasis != null && quantityBasis.trim().isNotEmpty) 'quantity_basis': quantityBasis.trim(),
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => PreparationItem.fromJson(_map(d)),
      );

  Future<PreparationItem> replaceItem(String id, PreparationItem item, PreparationItemInput input) => _call(
        () => _dio.post('${_job(id)}/preparation-items/${item.id}/replace',
            data: {...input.toJson(), 'expected_version': item.version}),
        (d) => PreparationItem.fromJson(_map(d)),
      );

  Future<PreparationItem> rejectItem(String id, PreparationItem item, {String? note}) => _call(
        () => _dio.post('${_job(id)}/preparation-items/${item.id}/reject', data: {
          'expected_version': item.version,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => PreparationItem.fromJson(_map(d)),
      );

  Future<ItemEvidenceResult> requestItemEvidence(String id, PreparationItem item,
          {required String category, required String prompt, required String reason}) =>
      _call(
        () => _dio.post('${_job(id)}/preparation-items/${item.id}/request-evidence', data: {
          'expected_version': item.version,
          'category': category,
          'prompt': prompt.trim(),
          'reason': reason.trim(),
        }),
        (d) => ItemEvidenceResult.fromJson(_map(d)),
      );

  Future<PreparationItem> confirmCatalogueMatch(String id, PreparationItem item, String productId) => _call(
        () => _dio.post('${_job(id)}/preparation-items/${item.id}/catalogue-match',
            data: {'product_id': productId, 'expected_version': item.version}),
        (d) => PreparationItem.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ briefs
  Future<Brief> previewBrief(String id) =>
      _call(() => _dio.post('${_job(id)}/briefs/preview'), (d) => Brief.fromJson(_map(d)));

  Future<List<Brief>> briefs(String id) => _call(() => _dio.get('${_job(id)}/briefs'), (d) => _list(d, Brief.fromJson));

  Future<Brief> brief(String id, String briefId) =>
      _call(() => _dio.get('${_job(id)}/briefs/$briefId'), (d) => Brief.fromJson(_map(d)));

  /// Publishes exactly the previewed snapshot (quoting its digest).
  /// The printable brief (inert HTML), fetched with the signed-in user's token as
  /// bytes — never through a URL carrying credentials.
  Future<DownloadedFile> exportBrief(String id, String briefId, {int? revisionNumber}) async {
    try {
      final r = await _dio.get<List<int>>('${_job(id)}/briefs/$briefId/export',
          options: Options(responseType: ResponseType.bytes, headers: {'Accept': 'text/html'}));
      final fallback = 'service-brief${revisionNumber == null ? '' : '-r$revisionNumber'}.html';
      return DownloadedFile(
        bytes: Uint8List.fromList(r.data ?? const []),
        filename: filenameFromDisposition(r.headers.value('content-disposition'), fallback),
        contentType: 'text/html;charset=utf-8',
      );
    } on DioException catch (e) {
      // Error bodies arrive as bytes here; decode them into the usual API error.
      final data = e.response?.data;
      if (data is List<int>) {
        Object? body;
        try {
          body = jsonDecode(utf8.decode(data));
        } catch (_) {}
        throw ApiError.fromResponse(e.response?.statusCode, body);
      }
      throw ApiError.from(e)!;
    }
  }

  Future<Brief> publishBrief(String id, Brief preview) => _call(
        () => _dio.post('${_job(id)}/briefs/${preview.id}/publish', data: {'content_digest': preview.contentDigest}),
        (d) => Brief.fromJson(_map(d)),
      );

  Future<BriefAckResult> acknowledgeBrief(String id, String briefId,
          {required String kind, String? note, Map<String, dynamic>? requestedView}) =>
      _call(
        () => _dio.post('${_job(id)}/briefs/$briefId/acknowledgements', data: {
          'kind': kind,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
          'requested_view': ?requestedView,
        }),
        (d) => BriefAckResult.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ scope
  Future<List<ScopeRevision>> scopes(String id) =>
      _call(() => _dio.get('${_job(id)}/scopes'), (d) => _list(d, ScopeRevision.fromJson));

  Future<ScopeRevision> proposeScope(String id, ScopeInput input) =>
      _call(() => _dio.post('${_job(id)}/scopes', data: input.toJson()), (d) => ScopeRevision.fromJson(_map(d)));

  /// The owner's decision on ONE exact revision (bound by its digest).
  Future<ScopeDecision> decideScope(String id, ScopeRevision revision, String decision,
          {String? note, required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/scopes/${revision.id}/decision',
            data: {
              'decision': decision,
              'revision_digest': revision.contentDigest,
              if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
            },
            options: _idem(idempotencyKey)),
        (d) => ScopeDecision.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ visits
  Future<List<VisitEvent>> visits(String id) =>
      _call(() => _dio.get('${_job(id)}/visits'), (d) => _list(d, VisitEvent.fromJson));

  Future<VisitResult> recordVisit(String id, String kind, DateTime occurredAt,
          {String? note, required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/visits',
            data: {
              'kind': kind,
              'occurred_at': occurredAt.toUtc().toIso8601String(),
              if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
            },
            options: _idem(idempotencyKey)),
        (d) => VisitResult.fromJson(_map(d)),
      );

  Future<ContestResult> contestVisit(String id, String eventId, String reason, {required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/visits/$eventId/contest',
            data: {'reason': reason.trim()}, options: _idem(idempotencyKey)),
        (d) => ContestResult.fromJson(_map(d)),
      );

  // ------------------------------------------------------------------ feedback
  Future<FeedbackOverview> feedback(String id) =>
      _call(() => _dio.get('${_job(id)}/feedback'), (d) => FeedbackOverview.fromJson(_map(d)));

  /// Replaces the caller's draft. Unanswered dimensions are omitted (never zero).
  Future<FeedbackOverview> saveFeedbackDraft(String id, String direction,
          {required Map<String, Object> ratings, String? narrative, int? expectedVersion}) =>
      _call(
        () => _dio.put('${_job(id)}/feedback/$direction', data: {
          'ratings': ratings,
          if (narrative != null && narrative.trim().isNotEmpty) 'narrative': narrative.trim(),
          'expected_version': ?expectedVersion,
        }),
        (d) => FeedbackOverview.fromJson(_map(d)),
      );

  Future<FeedbackOverview> submitFeedback(String id, String direction,
          {int? expectedVersion, required String idempotencyKey}) =>
      _call(
        () => _dio.post('${_job(id)}/feedback/$direction/submit',
            data: {'expected_version': ?expectedVersion}, options: _idem(idempotencyKey)),
        (d) => FeedbackOverview.fromJson(_map(d)),
      );

  Future<Review> respondToFeedback(String feedbackId, String kind, String text) => _call(
        () => _dio.post('/service-feedback/$feedbackId/responses', data: {'kind': kind, 'text': text.trim()}),
        (d) => Review.fromJson(_map(d)),
      );

  Future<FeedbackReport> reportFeedback(String feedbackId, String category, String reason,
          {bool restrictContent = false}) =>
      _call(
        () => _dio.post('/service-feedback/$feedbackId/reports',
            data: {'category': category, 'reason': reason.trim(), 'restrict_content': restrictContent}),
        (d) => FeedbackReport.fromJson(_map(d)),
      );
}
