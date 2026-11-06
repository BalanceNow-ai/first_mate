// Live updates (off by default), printable brief export, another organisation's
// records and job documents — in the real app shell, fed with captured payloads.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';

import '../../helpers/fakes.dart';
import 'sj_test_helpers.dart';

/// The live-updates-off job (a second captured job): the contractor's GETs for it.
String get j4 => sjMap('job_contractor_no_brief')['id'] as String;

FakeBackend snapshotBackend(String job, {Object briefs = const [], String measurements = 'measurements_contractor_no_brief',
    Object preparation = const []}) {
  final b = contractorBackend();
  final q = '/service-jobs/$j4';
  b.json('GET $q', 200, sj(job));
  b.json('GET $q/briefs', 200, briefs);
  b.json('GET $q/measurements', 200, sj(measurements));
  b.json('GET $q/preparation-items', 200, preparation);
  for (final path in ['evidence-requests', 'observations', 'scopes', 'visits']) {
    b.json('GET $q/$path', 200, []);
  }
  b.json('GET $q/assets', 200, {'items': [], 'total': 0});
  b.json('GET $q/feedback', 200, sj('feedback_not_eligible'));
  return b;
}

void main() {
  final p = '/service-jobs/$jobId';

  testWidgets('contractor: no brief published yet — says so plainly', (tester) async {
    final app = SjApp(tester, snapshotBackend('job_contractor_no_brief'));
    await app.start('/contractor/jobs/$j4/brief');
    expect(find.textContaining("The owner hasn't published a brief yet. Until they do"), findsOneWidget);
    expect(find.text("The owner hasn't published a brief yet. You will see it here when they do."), findsOneWidget);
    expect(find.textContaining('Showing the brief published on'), findsNothing);
  });

  testWidgets('contractor: live updates off — the banner names the brief date', (tester) async {
    final job = sjMap('job_contractor_brief_snapshot');
    final app = SjApp(tester, snapshotBackend('job_contractor_brief_snapshot'));
    await app.start('/contractor/jobs/$j4/measurements');
    final date = formatDate(DateTime.parse(job['snapshot_published_at'] as String));
    expect(find.textContaining('Showing the brief published on $date'), findsOneWidget);
  });

  testWidgets('contractor: live updates on — the banner says live', (tester) async {
    final app = SjApp(tester, contractorBackend());
    await app.start('/contractor/jobs/$jobId/brief');
    expect(find.textContaining('Live: you see the shared sections as they are now'), findsOneWidget);
  });

  testWidgets('owner: the invitation defaults to live updates off, explained, and the preview repeats it',
      (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/assignments', 200, []);
    backend.json('POST $p/assignments/preview', 200, sj('sharing_preview_snapshot'));
    backend.json('POST $p/assignments', 201, sj('assignment_invited_snapshot'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/sharing');
    final sw = tester.widget<SwitchListTile>(find.widgetWithText(SwitchListTile, 'Live updates'));
    expect(sw.value, isFalse, reason: 'off by default');
    expect(find.textContaining('as of the brief you publish'), findsWidgets);
    await app.tap(find.textContaining((sjList('directory').first['name']) as String));
    await app.tap(find.text('Preview what they will see'));
    final body = backend.calls('POST $p/assignments/preview').single.body as Map;
    expect(body['live_updates'], isFalse);
    final note = sjMap('sharing_preview_snapshot')['live_updates_note'] as String;
    expect(find.textContaining(note), findsOneWidget);
    await app.tap(find.text('Send invitation'));
    expect((backend.calls('POST $p/assignments').single.body as Map)['live_updates'], isFalse);
  });

  testWidgets('owner: turning live updates on is explicit and changes the explanation', (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/assignments', 200, []);
    backend.json('POST $p/assignments/preview', 200, sj('sharing_preview'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/sharing');
    await app.tap(find.widgetWithText(SwitchListTile, 'Live updates'));
    expect(find.textContaining('including every change you make later'), findsOneWidget);
    await app.tap(find.textContaining((sjList('directory').first['name']) as String));
    await app.tap(find.text('Preview what they will see'));
    expect((backend.calls('POST $p/assignments/preview').single.body as Map)['live_updates'], isTrue);
  });

  testWidgets('printable brief: fetched with the token as bytes, then handed over as a file', (tester) async {
    final backend = contractorBackend();
    final brief = sjList('briefs_contractor').last;
    backend.json('GET $p/briefs/${brief['id']}/export', 200, '<html>brief</html>');
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/brief');
    await app.tap(find.text('Download printable brief'));
    final call = backend.calls('GET $p/briefs/${brief['id']}/export').single;
    expect(call.authorization, 'Bearer token-a');
    expect(call.query, isEmpty, reason: 'no token in the URL');
    expect(app.saved.single.filename, endsWith('.html'));
    expect(app.saved.single.bytes, isNotEmpty);
    expect(app.opener.opened, isEmpty, reason: 'never opened as a URL');
    expect(find.textContaining('Downloaded'), findsOneWidget);
  });

  testWidgets('printable brief: the owner can export a published revision; failures are plain', (tester) async {
    final backend = ownerBackend();
    final published = sjList('briefs').firstWhere((b) => b['status'] == 'published');
    backend.json('GET $p/briefs/${published['id']}/export', 404, {'detail': 'Brief not found', 'code': 'not_found'});
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/brief');
    await app.tap(find.text('Download printable brief'));
    expect(backend.calls('GET $p/briefs/${published['id']}/export'), hasLength(1));
    expect(find.textContaining('Could not download the printable brief'), findsOneWidget);
    expect(app.saved, isEmpty);
  });

  testWidgets("contractor: another organisation's measurements and confirmations show without names",
      (tester) async {
    final app = SjApp(tester,
        snapshotBackend('job_contractor_live', measurements: 'measurements_other_org',
            preparation: sj('preparation_items_other_org') as Object));
    await app.start('/contractor/jobs/$j4/measurements');
    expect(find.textContaining('Live: you see the shared sections'), findsOneWidget);
    expect(find.text('Another organisation (names are not shared)'), findsOneWidget, reason: 'Cable gauge');
    expect(find.textContaining('by another organisation (names are not shared)'), findsNWidgets(2));
    app.go('/contractor/jobs/$j4/preparation');
    await app.settle();
    expect(find.textContaining('by another organisation (names are not shared)'), findsOneWidget);
  });

  testWidgets('capture: upload a document (PDF) → job_document intent → PUT → processed', (tester) async {
    final backend = ownerBackend();
    final intent = sjMap('asset_pdf_intent');
    final assetId = (intent['asset'] as Map)['id'];
    backend.json('POST $p/assets/intents', 201, intent);
    backend.json('PUT /service-assets/$assetId/content', 202, sj('asset_pdf_received'));
    backend.json('GET /service-assets/$assetId', 200, sj('asset_pdf_processed'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/capture');
    final extra = find.text('Upload a document (PDF)');
    await app.tap(extra.last);
    expect(app.picker.documentCalls, 1);
    final body = backend.calls('POST $p/assets/intents').single.body as Map;
    expect(body['purpose'], 'job_document');
    expect(body['content_type'], 'application/pdf');
    expect(backend.calls('PUT /service-assets/$assetId/content'), hasLength(1));
    expect(find.text('Document added'), findsOneWidget);
  });

  testWidgets('capture: a refused PDF says why in plain words', (tester) async {
    final backend = ownerBackend();
    final intent = sjMap('asset_pdf_rejected_intent');
    final assetId = (intent['asset'] as Map)['id'];
    backend.json('POST $p/assets/intents', 201, intent);
    backend.json('PUT /service-assets/$assetId/content', 202, sj('asset_pdf_rejected_received'));
    backend.json('GET /service-assets/$assetId', 200, sj('asset_pdf_rejected_processed'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/capture');
    await app.tap(find.text('Upload a document (PDF)').last);
    expect(find.textContaining('Document rejected: ${rejectionReasonLabel('active_pdf_content')}'), findsOneWidget);
    expect(find.textContaining('Rejected: ${rejectionReasonLabel('active_pdf_content')}'), findsOneWidget);
  });
}
