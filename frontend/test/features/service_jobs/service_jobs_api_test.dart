// The typed client sends exactly the server's contract (versions, digests,
// idempotency keys, integer minor units) and the upload controller follows
// intent → PUT bytes → poll status, with retry after a failed PUT.
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/service_jobs/data/media_picker.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/tabs/scope_tab.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../helpers/fakes.dart';
import 'sj_test_helpers.dart';

void main() {
  late FakeBackend backend;
  late ProviderContainer container;
  late ServiceJobsApi api;
  final p = '/service-jobs/$jobId';

  setUp(() async {
    backend = ownerBackend();
    container = ProviderContainer(overrides: [
      ...testOverrides(gateway: fixtureGateway(), backend: backend),
      uploadPollIntervalProvider.overrideWithValue(Duration.zero),
    ]);
    container.read(authControllerProvider);
    // Signed in (the user-scoped upload state resets when the user changes).
    await until(() => container.read(currentUserIdProvider) != null);
    api = container.read(serviceJobsApiProvider);
  });
  tearDown(() => container.dispose());

  test('idempotency keys are valid and unique', () {
    final a = newIdempotencyKey('scope');
    final b = newIdempotencyKey('scope');
    expect(a, isNot(b));
    expect(RegExp(r'^[A-Za-z0-9_\-:.]{8,100}$').hasMatch(a), isTrue);
  });

  test('money input becomes integer minor units without floating point', () {
    expect(parseMinorUnits('95'), 9500);
    expect(parseMinorUnits('95.5'), 9550);
    expect(parseMinorUnits(r'$1,234.05'), 123405);
    expect(parseMinorUnits('0.1'), 10);
    expect(parseMinorUnits('12.345'), isNull);
    expect(parseMinorUnits('abc'), isNull);
  });

  test('create job sends the vessel and entry point; unset fields are omitted', () async {
    backend.json('POST /service-jobs/', 201, sj('job_created'));
    final job = await api.createJob(const JobDraft(vesselId: 'v1', entryPoint: 'vessel', title: ' Leak ', urgency: 'soon'));
    expect(job.status, 'draft');
    final body = backend.calls('POST /service-jobs/').single.body as Map;
    expect(body, {'vessel_id': 'v1', 'entry_point': 'vessel', 'title': 'Leak', 'issue_description': '', 'urgency': 'soon'});
  });

  test('a stale edit surfaces the 409 version_conflict code', () async {
    backend.json('PATCH $p', 409, sj('error_version_conflict'));
    await expectLater(
      api.updateJob(jobId, 1, {'title': 'x'}),
      throwsA(isA<ApiError>().having((e) => e.code, 'code', 'version_conflict')),
    );
    expect((backend.calls('PATCH $p').single.body as Map)['expected_version'], 1);
  });

  test('scope decision quotes the exact revision digest with an Idempotency-Key', () async {
    final scope = ScopeRevision.fromJson(sjMap('scope_proposed'));
    backend.json('POST $p/scopes/${scope.id}/decision', 201, sj('scope_decision_accepted'));
    final d = await api.decideScope(jobId, scope, 'accepted', note: 'Go ahead', idempotencyKey: 'helm-scope-abcdef12');
    expect(d.decision, 'accepted');
    final call = backend.calls('POST $p/scopes/${scope.id}/decision').single;
    expect(call.headers['Idempotency-Key'], 'helm-scope-abcdef12');
    expect(call.body, {'decision': 'accepted', 'revision_digest': scope.contentDigest, 'note': 'Go ahead'});
  });

  test('scope proposal sends integer minor units and a currency', () async {
    backend.json('POST $p/scopes', 201, sj('scope_proposed'));
    await api.proposeScope(
      jobId,
      ScopeInput(
        summary: 'Replace hose',
        tasks: const [(description: 'Inspect far end', needsSiteInspection: true)],
        estimateLines: [
          EstimateLineInput(description: 'Labour', kind: 'labour', quantity: '1.5', unit: 'hour', unitPriceMinor: parseMinorUnits('95')),
          const EstimateLineInput(description: 'Parts', kind: 'parts', amountMinor: 4250),
        ],
        currency: 'NZD',
      ),
    );
    final body = backend.calls('POST $p/scopes').single.body as Map;
    expect(body['estimate_lines'], [
      {'description': 'Labour', 'kind': 'labour', 'quantity': '1.5', 'unit': 'hour', 'unit_price_minor': 9500},
      {'description': 'Parts', 'kind': 'parts', 'amount_minor': 4250},
    ]);
    expect(body['tasks'], [
      {'description': 'Inspect far end', 'needs_site_inspection': true},
    ]);
    expect(body['currency'], 'NZD');
  });

  test('brief publish quotes the preview digest; visits send UTC and an Idempotency-Key', () async {
    final preview = Brief.fromJson(sjMap('brief_preview'));
    backend.json('POST $p/briefs/${preview.id}/publish', 200, sj('brief_published'));
    await api.publishBrief(jobId, preview);
    expect(backend.calls('POST $p/briefs/${preview.id}/publish').single.body, {'content_digest': preview.contentDigest});

    backend.json('POST $p/visits', 201, sj('visit_attended'));
    await api.recordVisit(jobId, 'attended', DateTime.utc(2026, 11, 6, 1), idempotencyKey: 'helm-visit-12345678');
    final v = backend.calls('POST $p/visits').single;
    expect((v.body as Map)['occurred_at'], '2026-11-06T01:00:00.000Z');
    expect(v.headers['Idempotency-Key'], 'helm-visit-12345678');
  });

  test('feedback draft never turns a missing answer into zero', () async {
    backend.json('PUT $p/feedback/owner_to_contractor', 200, sj('feedback_owner_draft'));
    await api.saveFeedbackDraft(jobId, 'owner_to_contractor',
        ratings: {'communication_clarity': 5, 'invoice_clarity_and_scope_relationship': 'not_applicable'},
        expectedVersion: 0);
    final body = backend.calls('PUT $p/feedback/owner_to_contractor').single.body as Map;
    expect(body['ratings'], {'communication_clarity': 5, 'invoice_clarity_and_scope_relationship': 'not_applicable'});
    expect(body.containsKey('narrative'), isFalse);
  });

  test('upload: intent → PUT bytes to the server URL → poll until available', () async {
    final intent = sjMap('asset_png_intent');
    final assetId = (intent['asset'] as Map)['id'];
    backend.json('POST $p/assets/intents', 201, intent);
    backend.json('PUT /service-assets/$assetId/content', 202, sj('asset_png_received'));
    var polls = 0;
    backend.on('GET /service-assets/$assetId', (_) {
      polls++;
      return FakeResponse(200, sj(polls < 2 ? 'asset_png_received' : 'asset_png_processed'));
    });
    final bytes = Uint8List.fromList([137, 80, 78, 71, 1, 2, 3]);
    final done = await container
        .read(uploadsProvider(jobId).notifier)
        .upload(PickedMedia(bytes: bytes, name: 'overview.png', mimeType: 'image/png'), requestId: 'req-1');
    expect(done!.isAvailable, isTrue);
    final intentCall = backend.calls('POST $p/assets/intents').single;
    expect(intentCall.headers['Idempotency-Key'], startsWith('helm-upload-'));
    expect(intentCall.body, {
      'purpose': 'job_photo',
      'evidence_request_id': 'req-1',
      'filename': 'overview.png',
      'content_type': 'image/png',
      'size_bytes': bytes.length,
    });
    final put = backend.calls('PUT /service-assets/$assetId/content').single;
    expect(put.body, bytes);
    expect(put.headers['content-type'] ?? put.headers['Content-Type'], 'application/octet-stream');
    expect(polls, 2);
    final task = container.read(uploadsProvider(jobId)).single;
    expect(task.stage, UploadStage.done);
    expect(task.bytes, isNull, reason: 'bytes are released once the server has them');
  });

  test('upload: a failed PUT keeps the bytes and can be retried', () async {
    final intent = sjMap('asset_jpeg_intent');
    final assetId = (intent['asset'] as Map)['id'];
    backend.json('POST $p/assets/intents', 201, intent);
    var fail = true;
    backend.on('PUT /service-assets/$assetId/content', (_) {
      if (fail) return const FakeResponse(503, {'detail': 'Storage unavailable', 'code': 'storage_unavailable'});
      return FakeResponse(202, sj('asset_jpeg_processed'));
    });
    final ctrl = container.read(uploadsProvider(jobId).notifier);
    final first = await ctrl.upload(PickedMedia(bytes: Uint8List.fromList([1, 2, 3]), name: 'label.jpg'));
    expect(first, isNull);
    final failed = container.read(uploadsProvider(jobId)).single;
    expect(failed.stage, UploadStage.failed);
    expect(failed.bytes, isNotNull);
    fail = false;
    final retried = await ctrl.retry(failed.localId);
    expect(retried!.isAvailable, isTrue);
    expect(backend.calls('POST $p/assets/intents'), hasLength(1), reason: 'the retry reuses the same intent');
    expect(backend.calls('PUT /service-assets/$assetId/content'), hasLength(2));
  });

  test('relative signed URLs resolve against the API origin', () {
    expect(api.resolve('/api/v1/service-assets/local-download?k=x').toString(),
        'http://api.test/api/v1/service-assets/local-download?k=x');
    expect(api.resolve('http://localhost:18080/helm-private/x?sig=1').toString(), 'http://localhost:18080/helm-private/x?sig=1');
  });
}
