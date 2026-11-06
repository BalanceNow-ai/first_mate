// Client/contract hardening of the service-jobs client, against REAL captured
// payloads (scripts/capture_api_fixtures_service_jobs.py); where a case cannot be
// produced by the local stack, one server flag of a captured payload is varied and
// the test says so.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';

import '../../helpers/fakes.dart';
import 'sj_test_helpers.dart';

void main() {
  final p = '/service-jobs/$jobId';

  // ------------------------------------------------------------ recorder vs confirmer
  group('another organisation: recorder and confirmer are separate', () {
    test('owner-recorded, other-organisation-confirmed (captured): the owner stays the recorder', () {
      final ms = [for (final m in sjList('measurements_other_org')) Measurement.fromJson(m)];
      final run = ms.singleWhere((m) => m.component == 'Port light cable run');
      expect(run.recordedByOtherOrganization, isFalse);
      expect(run.recordedByAnotherOrganization, isFalse);
      expect(run.confirmedByOtherOrganization, isTrue);
      expect(run.confirmedByAnotherOrganization, isTrue);
      expect(run.confirmation!.confirmedBy, isNull);
      final gauge = ms.singleWhere((m) => m.component == 'Cable gauge');
      expect(gauge.recordedByAnotherOrganization, isTrue);
      expect(gauge.confirmedByAnotherOrganization, isTrue);
    });

    test('the confirmer flag is read from the server, never inferred from the recorder flag', () {
      // A captured owner-recorded measurement with exactly the server's masking for a
      // foreign confirmer (recorder unmasked, confirmed_by withheld).
      final m = sjList('measurements').firstWhere((m) => (m['provenance'] as Map)['recorded_by_role'] == 'owner');
      m['confirmation'] = {'confirmed_by': null, 'confirmed_at': '2026-11-06T06:30:00Z', 'method': 'contractor_site'};
      m['recorded_by_other_organization'] = false;
      m['confirmed_by_other_organization'] = true;
      final parsed = Measurement.fromJson(m);
      expect(parsed.confirmedByAnotherOrganization, isTrue);
      expect(parsed.recordedByAnotherOrganization, isFalse);
      // …and a missing confirmer is not "another organisation" just because the
      // recorder was.
      m['confirmed_by_other_organization'] = false;
      m['recorded_by_other_organization'] = true;
      expect(Measurement.fromJson(m).confirmedByAnotherOrganization, isFalse);
    });

    test('preparation items carry confirmed_by_other_organization', () {
      final other = PreparationItem.fromJson(sjList('preparation_items_other_org').single);
      expect(other.confirmedByOtherOrganization, isTrue);
      for (final i in sjList('preparation_items_owner_view')) {
        expect(
          PreparationItem.fromJson(i).confirmedByOtherOrganization,
          isFalse,
          reason: 'the owner sees every person',
        );
      }
      // A null confirmed_by alone (e.g. never confirmed) is not another organisation.
      final own = sjMap('preparation_item_confirmed')..['confirmed_by'] = null;
      expect(PreparationItem.fromJson(own).confirmedByOtherOrganization, isFalse);
    });

    testWidgets('contractor: only the confirmation of the owner-recorded run is attributed to another organisation', (
      tester,
    ) async {
      final backend = contractorBackend();
      backend.json('GET $p/measurements', 200, sj('measurements_other_org'));
      final app = SjApp(tester, backend);
      await app.start('/contractor/jobs/$jobId/measurements');
      final run = find.ancestor(of: find.textContaining('Port light cable run'), matching: find.byType(Card)).first;
      expect(
        find.descendant(of: run, matching: find.text('Another organisation (names are not shared)')),
        findsNothing,
      );
      expect(
        find.descendant(of: run, matching: find.textContaining('by another organisation (names are not shared)')),
        findsOneWidget,
      );
    });
  });

  // ------------------------------------------------------------ interrupted / rejected uploads
  Map<String, dynamic> pendingAsset({required String purpose, String? expires}) {
    final list = sjMap('assets_list');
    final a = (list['items'] as List).cast<Map<String, dynamic>>().first
      ..['id'] = '00000000-0000-4000-8000-00000000d0c0'
      ..['purpose'] = purpose
      ..['status'] = 'upload_pending'
      ..['uploaded_by_me'] = true
      ..['caption'] = purpose == 'job_document' ? 'Pump manual' : 'Pump label'
      ..['detected_type'] = null
      ..['width'] = null
      ..['height'] = null
      ..['size_bytes'] = null
      ..['quality'] = <String, dynamic>{}
      ..['upload_expires_at'] = expires ?? '2099-01-01T00:00:00Z';
    return a;
  }

  FakeBackend withAssets(List<Map<String, dynamic>> items) {
    final backend = ownerBackend();
    backend.json('GET $p/assets', 200, {...sjMap('assets_list'), 'items': items, 'total': items.length});
    return backend;
  }

  group('interrupted and rejected uploads', () {
    testWidgets('an interrupted PDF is finished with the document picker and PDF wording', (tester) async {
      final a = pendingAsset(purpose: 'job_document');
      final backend = withAssets([a]);
      backend.json('PUT /service-assets/${a['id']}/content', 202, {...a, 'status': 'quarantined'});
      backend.json('GET /service-assets/${a['id']}', 200, sj('asset_pdf_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      expect(find.textContaining('Choose the same document (PDF) again'), findsOneWidget);
      await app.tap(find.text('Finish upload'));
      expect(app.picker.documentCalls, 1, reason: 'a PDF can only be re-chosen with the document picker');
      expect(app.picker.calls, isEmpty, reason: 'the photo gallery cannot offer the PDF');
      expect(backend.calls('PUT /service-assets/${a['id']}/content'), hasLength(1));
    });

    testWidgets('an interrupted photo is finished from the gallery (not the document picker)', (tester) async {
      final a = pendingAsset(purpose: 'job_photo');
      final backend = withAssets([a]);
      backend.json('PUT /service-assets/${a['id']}/content', 202, {...a, 'status': 'quarantined'});
      backend.json('GET /service-assets/${a['id']}', 200, sj('asset_png_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      expect(find.textContaining('Choose the same photo again'), findsOneWidget);
      await app.tap(find.text('Finish upload'));
      expect(app.picker.calls, [false]);
      expect(app.picker.documentCalls, 0);
    });

    testWidgets('a rejected PDF is replaced with the document picker, never the camera', (tester) async {
      final rejected = sjMap('asset_pdf_rejected_processed');
      final backend = withAssets([rejected]);
      final intent = sjMap('asset_pdf_intent');
      final newId = (intent['asset'] as Map)['id'];
      backend.json('POST $p/assets/intents', 201, intent);
      backend.json('PUT /service-assets/$newId/content', 202, sj('asset_pdf_received'));
      backend.json('GET /service-assets/$newId', 200, sj('asset_pdf_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      expect(find.text('Retake'), findsNothing, reason: 'a document is not retaken with a camera');
      await app.tap(find.text('Choose another document'));
      expect(app.picker.documentCalls, 1);
      expect(app.picker.calls, isEmpty);
      expect((backend.calls('POST $p/assets/intents').single.body as Map)['purpose'], 'job_document');
    });

    testWidgets('an expired intent (upload_expires_at passed) is abandoned and a fresh one started', (tester) async {
      final a = pendingAsset(purpose: 'job_document', expires: '2020-01-01T00:00:00Z');
      final backend = withAssets([a]);
      final intent = sjMap('asset_pdf_intent');
      final newId = (intent['asset'] as Map)['id'];
      backend.json('DELETE /service-assets/${a['id']}', 204, null);
      backend.json('POST $p/assets/intents', 201, intent);
      backend.json('PUT /service-assets/$newId/content', 202, sj('asset_pdf_received'));
      backend.json('GET /service-assets/$newId', 200, sj('asset_pdf_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      await app.tap(find.text('Finish upload'));
      expect(
        backend.calls('PUT /service-assets/${a['id']}/content'),
        isEmpty,
        reason: 'never re-PUT to an expired link',
      );
      expect(backend.calls('DELETE /service-assets/${a['id']}'), hasLength(1), reason: 'the old intent is abandoned');
      final fresh = backend.calls('POST $p/assets/intents').single;
      expect(fresh.headers['Idempotency-Key'], startsWith('helm-upload-'));
      expect((fresh.body as Map)['purpose'], 'job_document');
      expect((fresh.body as Map)['caption'], 'Pump manual');
      expect(backend.calls('PUT /service-assets/$newId/content'), hasLength(1));
    });

    testWidgets('a 410 upload_intent_expired on the PUT starts a fresh intent instead of retrying the old link', (
      tester,
    ) async {
      final a = pendingAsset(purpose: 'job_photo');
      final backend = withAssets([a]);
      final intent = sjMap('asset_png_intent');
      final newId = (intent['asset'] as Map)['id'];
      backend.json('PUT /service-assets/${a['id']}/content', 410, {
        'detail': 'This upload link has expired; start the upload again',
        'code': 'upload_intent_expired',
      });
      backend.json('DELETE /service-assets/${a['id']}', 204, null);
      backend.json('POST $p/assets/intents', 201, intent);
      backend.json('PUT /service-assets/$newId/content', 202, sj('asset_png_received'));
      backend.json('GET /service-assets/$newId', 200, sj('asset_png_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      await app.tap(find.text('Finish upload'));
      expect(backend.calls('PUT /service-assets/${a['id']}/content'), hasLength(1));
      expect(backend.calls('DELETE /service-assets/${a['id']}'), hasLength(1));
      expect(backend.calls('POST $p/assets/intents'), hasLength(1));
      expect(backend.calls('PUT /service-assets/$newId/content'), hasLength(1));
      expect(find.textContaining('Upload failed'), findsNothing);
    });

    testWidgets('a failed intent is retried with the same Idempotency-Key (one upload action, one key)', (
      tester,
    ) async {
      final backend = ownerBackend();
      final intent = sjMap('asset_png_intent');
      final newId = (intent['asset'] as Map)['id'];
      var attempts = 0;
      backend.on('POST $p/assets/intents', (_) {
        attempts++;
        return attempts == 1
            ? const FakeResponse(503, {'detail': 'Service unavailable', 'code': 'unavailable'})
            : FakeResponse(201, intent);
      });
      backend.json('PUT /service-assets/$newId/content', 202, sj('asset_png_received'));
      backend.json('GET /service-assets/$newId', 200, sj('asset_png_processed'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      await app.tap(find.text('Upload an extra photo'));
      expect(find.text('Retry upload'), findsOneWidget);
      await app.tap(find.text('Retry upload'));
      final keys = [for (final c in backend.calls('POST $p/assets/intents')) c.headers['Idempotency-Key']];
      expect(keys, hasLength(2));
      expect(keys.toSet(), hasLength(1), reason: 'a retry of the same upload reuses its key');
      expect(backend.calls('PUT /service-assets/$newId/content'), hasLength(1));
      // A new upload action gets a new key.
      await app.tap(find.text('Upload an extra photo'));
      expect(backend.calls('POST $p/assets/intents').last.headers['Idempotency-Key'], isNot(keys.first));
    });
  });

  // ------------------------------------------------------------ add to cart
  group('add to cart only for live items on live jobs', () {
    Finder card(String name) => find.ancestor(of: find.text(name), matching: find.byType(Card)).first;
    Finder addIn(String name) => find.descendant(of: card(name), matching: find.text('Add to cart'));

    testWidgets('a rejected item offers no purchase and says why; live items do (owner view)', (tester) async {
      final backend = ownerBackend();
      backend.json('GET $p/preparation-items', 200, sj('preparation_items_owner_view'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/preparation');
      final items = sjList('preparation_items_owner_view');
      final rejected = items.singleWhere((i) => i['status'] == 'rejected')['name'] as String;
      expect(addIn(rejected), findsNothing);
      expect(
        find.descendant(of: card(rejected), matching: find.text('Not offered for purchase — this item is rejected.')),
        findsWidgets,
      );
      final confirmed = items.singleWhere((i) => i['status'] == 'contractor_confirmed')['name'] as String;
      expect(addIn(confirmed), findsOneWidget);
      // Exactly one button per active, in-stock candidate of a live item.
      final expected = [
        for (final i in items)
          if (const {'suggested', 'needs_evidence', 'contractor_confirmed'}.contains(i['status']))
            for (final c in (i['candidates'] as List).cast<Map>())
              if (c['is_active'] == true && c['in_stock'] == true) c,
      ].length;
      expect(find.text('Add to cart'), findsNWidgets(expected));
    });

    testWidgets('a cancelled job offers no purchase', (tester) async {
      final backend = ownerBackend();
      backend.json('GET $p', 200, sjMap('job_after_upload')..['status'] = 'cancelled');
      backend.json('GET $p/preparation-items', 200, sj('preparation_items_owner_view'));
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/preparation');
      expect(find.text('Add to cart'), findsNothing);
      expect(find.textContaining('this job is cancelled'), findsWidgets);
    });

    testWidgets('a candidate whose stated range excludes the recorded OD is not offered, with the reason', (
      tester,
    ) async {
      // The local catalogue has no product with a stated clamp range, so the captured
      // clamp candidate's dimension_check is set to the server's exclusion result.
      final items = sjList('preparation_items_owner_view');
      final clamps = items.singleWhere((i) => i['status'] == 'needs_evidence');
      final candidate = (clamps['candidates'] as List).cast<Map>().single;
      candidate['dimension_check'] = {
        'status': 'range_excludes_recorded_od',
        'reason': 'Stated range 20–25 mm does not include the recorded 32.5 mm hose OD',
      };
      final backend = ownerBackend();
      backend.json('GET $p/preparation-items', 200, items);
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/preparation');
      final name = clamps['name'] as String;
      expect(addIn(name), findsNothing);
      expect(
        find.descendant(of: card(name), matching: find.textContaining('does not include the recorded measurement')),
        findsOneWidget,
      );
    });
  });

  // ------------------------------------------------------------ 320 px
  group('320 px phone width: no overflow', () {
    for (final tab in [
      'overview',
      'capture',
      'measurements',
      'preparation',
      'sharing',
      'brief',
      'scope',
      'visits',
      'feedback',
    ]) {
      testWidgets('owner $tab', (tester) async {
        final app = SjApp(tester, ownerBackend());
        await app.start('/service-jobs/$jobId/$tab', size: const Size(320, 2400));
        expect(tester.takeException(), isNull);
      });
    }
    for (final tab in ['brief', 'requests', 'measurements', 'preparation', 'scope', 'visits', 'feedback']) {
      testWidgets('contractor $tab', (tester) async {
        final app = SjApp(tester, contractorBackend());
        await app.start('/contractor/jobs/$jobId/$tab', size: const Size(320, 2400));
        expect(tester.takeException(), isNull);
      });
    }
  });

  // ------------------------------------------------------------ analysis polling
  group('analysis polling', () {
    Map<String, dynamic> statusWithRun(String runStatus) {
      final s = sjMap('analysis_status');
      ((s['runs'] as List).last as Map)['status'] = runStatus;
      return s;
    }

    testWidgets('a run already in progress after a reload is followed until it finishes', (tester) async {
      final backend = ownerBackend();
      final status = statusWithRun('running');
      final runId = ((status['runs'] as List).last as Map)['id'];
      var current = status;
      backend.on('GET $p/analysis', (_) => FakeResponse(200, current));
      backend.on('GET $p/analysis/$runId', (_) {
        current = sjMap('analysis_status');
        return FakeResponse(200, sj('analysis_run'));
      });
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      expect(backend.calls('GET $p/analysis/$runId'), isNotEmpty, reason: 'polling resumes from the run status');
      expect(find.text('Analyse photos'), findsOneWidget, reason: 'the finished run frees the button');
    });

    testWidgets('leaving the page stops polling without touching disposed state', (tester) async {
      final backend = ownerBackend();
      final queued = sjMap('analysis_queued');
      final gate = Completer<void>();
      backend.json('POST $p/analysis', 202, queued);
      backend.on('GET $p/analysis/${queued['id']}', (_) async {
        await gate.future;
        return FakeResponse(200, sj('analysis_run'));
      });
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/capture');
      await app.tap(find.text('Analyse photos'));
      expect(backend.calls('GET $p/analysis/${queued['id']}'), hasLength(1));
      app.go('/service-jobs');
      await app.settle();
      gate.complete();
      await app.settle();
      expect(tester.takeException(), isNull);
      expect(backend.calls('GET $p/analysis/${queued['id']}'), hasLength(1), reason: 'no polling after leaving');
    });
  });

  // ------------------------------------------------------------ one key per action
  group('idempotency: one key per logical action', () {
    testWidgets('a retried scope decision reuses its key', (tester) async {
      final backend = ownerBackend();
      final scope = sjMap('scope_proposed');
      backend.json('GET $p/scopes', 200, [scope]);
      var attempts = 0;
      backend.on('POST $p/scopes/${scope['id']}/decision', (_) {
        attempts++;
        return attempts == 1
            ? const FakeResponse(503, {'detail': 'Service unavailable', 'code': 'unavailable'})
            : FakeResponse(201, sj('scope_decision_accepted'));
      });
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/scope');
      for (var i = 0; i < 2; i++) {
        await app.tap(find.text('Accept revision 1'));
        await app.tap(find.text('Accept this revision'));
      }
      final keys = [
        for (final c in backend.calls('POST $p/scopes/${scope['id']}/decision')) c.headers['Idempotency-Key'],
      ];
      expect(keys, hasLength(2));
      expect(keys.first, startsWith('helm-scope-'));
      expect(keys.toSet(), hasLength(1));
    });

    testWidgets('a retried feedback submission reuses its key', (tester) async {
      final backend = ownerBackend();
      backend.json('PUT $p/feedback/owner_to_contractor', 200, sj('feedback_owner_draft'));
      var attempts = 0;
      backend.on('POST $p/feedback/owner_to_contractor/submit', (_) {
        attempts++;
        return attempts == 1
            ? const FakeResponse(503, {'detail': 'Service unavailable', 'code': 'unavailable'})
            : FakeResponse(201, sj('feedback_owner_submitted'));
      });
      final app = SjApp(tester, backend);
      await app.start('/service-jobs/$jobId/feedback');
      await app.tap(find.text('5 · Excellent').first);
      for (var i = 0; i < 2; i++) {
        await app.tap(find.text('Submit review'));
        await app.tap(inDialog('Submit review'));
      }
      final keys = [
        for (final c in backend.calls('POST $p/feedback/owner_to_contractor/submit')) c.headers['Idempotency-Key'],
      ];
      expect(keys, hasLength(2));
      expect(keys.toSet(), hasLength(1));
    });
  });

  // ------------------------------------------------------------ access limits
  testWidgets('access details: client limits match the server schema', (tester) async {
    final app = SjApp(tester, ownerBackend());
    await app.start('/service-jobs/$jobId/sharing');
    await app.tap(find.text('Edit access and logistics'));
    int? limit(String label) => tester.widget<TextField>(find.widgetWithText(TextField, label)).maxLength;
    expect(limit('Marina'), 200);
    expect(limit('Parking and loading'), 500);
    expect(limit('Known hazards'), 1000);
    expect(limit('Other notes'), 1000);
    await app.tap(inDialog('Cancel'));
    await app.tap(find.text('Access credentials'));
    await app.tap(inDialog('Edit'));
    expect(limit('Gate code'), 100);
    expect(limit('Contact name'), 120);
    expect(limit('Contact phone'), 40);
    expect(limit('Exact location'), 300);
    expect(limit('Security notes'), 1000);
  });

  // ------------------------------------------------------------ pagination
  group('lists load more with the server limit/offset', () {
    final small = listPageSizeProvider.overrideWith((ref, list) => 1);

    testWidgets('jobs list', (tester) async {
      final backend = ownerBackend();
      final all = sjList('jobs_list_final');
      backend.on('GET /service-jobs/', (r) {
        final offset = int.parse('${r.query['offset'] ?? 0}');
        return FakeResponse(200, all.skip(offset).take(int.parse('${r.query['limit']}')).toList());
      });
      final app = SjApp(tester, backend, overrides: [small]);
      await app.start('/service-jobs');
      expect(find.text(all[0]['title'] as String), findsOneWidget);
      expect(find.text(all[1]['title'] as String), findsNothing);
      await app.tap(find.text('Load more jobs'));
      expect(backend.calls('GET /service-jobs/').last.query, {'limit': '1', 'offset': '1'});
      expect(find.text(all[1]['title'] as String), findsOneWidget);
      await app.tap(find.text('Load more jobs'));
      expect(find.text('Load more jobs'), findsNothing, reason: 'a short page ends the list');
    });

    testWidgets('contractor inbox', (tester) async {
      final backend = contractorBackend();
      backend.on(
        'GET /contractors/me/jobs',
        (r) => FakeResponse(
          200,
          r.query['offset'] == null ? sj('contractor_inbox_assigned') : sj('contractor_inbox_empty'),
        ),
      );
      final app = SjApp(tester, backend, overrides: [small]);
      await app.start('/contractor/inbox');
      await app.tap(find.text('Load more'));
      expect(backend.calls('GET /contractors/me/jobs').last.query, {'limit': '1', 'offset': '1'});
      expect(find.text('Load more'), findsNothing);
      expect(find.text(sjMap('contractor_inbox_assigned')['assigned'][0]['title'] as String), findsOneWidget);
    });

    testWidgets('organisation directory', (tester) async {
      final backend = ownerBackend();
      backend.json('GET $p/assignments', 200, []);
      final all = sjList('directory');
      backend.on('GET /contractors/directory', (r) {
        final offset = int.parse('${r.query['offset'] ?? 0}');
        return FakeResponse(200, all.skip(offset).take(1).toList());
      });
      final app = SjApp(tester, backend, overrides: [small]);
      await app.start('/service-jobs/$jobId/sharing');
      expect(find.textContaining(all[1]['name'] as String), findsNothing);
      await app.tap(find.text('More organisations'));
      expect(backend.calls('GET /contractors/directory').last.query['offset'], '1');
      expect(find.textContaining(all[1]['name'] as String), findsOneWidget);
    });
  });

  // ------------------------------------------------------------ scope currency
  testWidgets('a scope estimate can be in another ISO currency', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p/scopes', 200, []);
    backend.json('POST $p/scopes', 201, sj('scope_proposed'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/scope');
    await app.tapText('Propose a scope');
    await app.enter('Summary of the work *', 'Replace the outlet hose');
    await app.enter('Line 1 description', 'Call-out');
    await app.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('NZD')));
    await app.tap(find.text('AUD').last);
    await app.enter('Or amount (AUD)', '85');
    await app.tap(inDialog('Send to the owner'));
    final body = backend.calls('POST $p/scopes').single.body as Map;
    expect(body['currency'], 'AUD');
    expect(body['estimate_lines'], [
      {'description': 'Call-out', 'kind': 'labour', 'amount_minor': 8500},
    ]);
  });
}
