// Owner journeys through the real app (router, shell, providers) against REAL
// captured payloads: upload → reading → correction with server-recalculated
// sums → explanation → editable questions → explicit send; standalone limits;
// version conflicts and access errors.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';

import '../../helpers/fakes.dart';
import 'invoice_test_helpers.dart';

void main() {
  final extracted = invMap('invoice_extracted');
  final standaloneId = extracted['id'] as String;
  final assetId = (extracted['revision'] as Map)['source_asset_id'] as String;
  final jobDraft = invMap('invoice_job_with_draft');
  final jobId = jobDraft['id'] as String;
  final jobAssetId = (jobDraft['revision'] as Map)['source_asset_id'] as String;

  (InvoiceHarness, FakeBackend) setUp(WidgetTester tester, {Size size = const Size(1280, 8000)}) {
    final (backend, gateway) = ownerSession();
    backend.json('GET /service-assets/$assetId', 200, inv('standalone_asset_available'));
    backend.json('GET /service-assets/$jobAssetId', 200, inv('standalone_asset_available'));
    return (InvoiceHarness(tester, backend: backend, gateway: gateway), backend);
  }

  testWidgets('invoice list and the profile entry', (tester) async {
    final (app, backend) = setUp(tester);
    backend.json('GET /invoices', 200, inv('invoice_list'));
    await app.start();
    await app.go('/profile');
    expect(find.text('Invoices'), findsOneWidget);
    expect(find.text('Moderation'), findsNothing, reason: 'owners are not moderators');
    await app.tap(find.text('Invoices'));
    expect(app.location, '/invoices');
    expect(find.text('Harbour Marine invoice'), findsOneWidget);
    expect(find.textContaining('Not linked to a service job'), findsWidgets);
    expect(find.textContaining('Linked to a service job'), findsWidgets);
    expect(find.text('Understand an invoice'), findsOneWidget);
    await app.stop();
  });

  testWidgets('upload a PDF through the private-media path and start reading', (tester) async {
    final (backend, gateway) = ownerSession();
    final created = invMap('invoice_created');
    final asset = invMap('standalone_asset_intent');
    final id = (asset['asset'] as Map)['id'] as String;
    backend.json('POST /service-assets/invoice-intents', 201, asset);
    backend.json('PUT /service-assets/$id/content', 202, inv('standalone_asset_content_accepted'));
    backend.json('GET /service-assets/$id', 200, inv('standalone_asset_available'));
    backend.json('POST /invoices', 201, created);
    backend.json('POST /invoices/${created['id']}/extract', 202, inv('extraction_run_queued'));
    backend.json('GET /invoices/${created['id']}', 200, extracted);
    final app = InvoiceHarness(tester,
        backend: backend,
        gateway: gateway,
        overrides: [documentPickerProvider.overrideWithValue(() async => pickedPdf)]);
    await app.start();
    await app.go('/invoices/new?vessel_id=v1');
    expect(find.text('Not linked to a service job'), findsOneWidget);
    expect(find.textContaining('nobody else gets access'), findsOneWidget);
    await app.tap(find.text('Choose a PDF or photo'));
    expect(find.text('harbour-invoice.pdf'), findsOneWidget);
    await app.tap(find.text('Upload and read'));
    final intent = backend.calls('POST /service-assets/invoice-intents').single;
    expect(intent.headers['Idempotency-Key'], isNotNull);
    expect((intent.body as Map)['content_type'], 'application/pdf');
    expect((intent.body as Map).containsKey('job_id'), isFalse, reason: 'standalone upload');
    expect(backend.calls('PUT /service-assets/$id/content'), hasLength(1));
    final create = backend.calls('POST /invoices').single.body as Map;
    expect(create['asset_id'], id);
    expect(create['title'], 'Invoice');
    expect(backend.calls('POST /invoices/${created['id']}/extract').single.headers['Idempotency-Key'], isNotNull);
    expect(app.location, '/invoices/${created['id']}');
    expect(find.text('Read into a draft'), findsOneWidget);
    expect(find.textContaining('local test reader'), findsOneWidget);
    expect(find.text('1 value was hard to read'), findsOneWidget);
    await app.stop();
  });

  testWidgets('a rejected upload explains why and offers manual entry', (tester) async {
    final (backend, gateway) = ownerSession();
    final asset = invMap('standalone_asset_intent');
    final id = (asset['asset'] as Map)['id'] as String;
    backend.json('POST /service-assets/invoice-intents', 201, asset);
    backend.json('PUT /service-assets/$id/content', 202, inv('standalone_asset_content_accepted'));
    // The real asset with the status/reason the server sets when a PDF is refused.
    final rejected = copyOf(invMap('standalone_asset_available'))
      ..['status'] = 'rejected'
      ..['rejection_reason'] = 'active_pdf_content';
    backend.json('GET /service-assets/$id', 200, rejected);
    final app = InvoiceHarness(tester,
        backend: backend,
        gateway: gateway,
        overrides: [documentPickerProvider.overrideWithValue(() async => pickedPdf)]);
    await app.start();
    await app.go('/invoices/new');
    await app.tap(find.text('Choose a PDF or photo'));
    await app.tap(find.text('Upload and read'));
    expect(find.textContaining('active content'), findsOneWidget);
    expect(backend.calls('POST /invoices'), isEmpty);
    expect(find.text('Enter the details by hand instead'), findsOneWidget);
    await app.stop();
  });

  testWidgets('review side by side: low-certainty line → correct → server recalculates the sums', (tester) async {
    final (app, backend) = setUp(tester);
    final corrected = invMap('invoice_line_corrected');
    final clamp = (extracted['lines'] as List).cast<Map>().singleWhere((l) => l['description'] == 'S/S hose clamp 316');
    var current = extracted;
    backend.on('GET /invoices/$standaloneId', (_) => FakeResponse(200, current));
    backend.on('PATCH /invoices/$standaloneId/lines/${clamp['id']}', (_) {
      current = copyOf(corrected)..['explanation'] = invMap('invoice_standalone_explained')['explanation'];
      return FakeResponse(200, corrected);
    });
    backend.json('POST /invoices/$standaloneId/explain', 201, inv('explanation_standalone'));
    await app.start();
    await app.go('/invoices/$standaloneId/review');
    // Document and values side by side.
    expect(find.text('Invoice document (PDF · 1 page)'), findsOneWidget);
    expect(find.text('Open the document'), findsOneWidget);
    expect(find.textContaining('Page map'), findsOneWidget);
    expect(find.text('Needs your confirmation'), findsOneWidget);
    expect(find.text('Hard to read'), findsWidgets);
    final review = tester.widget<FilledButton>(find.ancestor(of: find.text('Mark as reviewed'), matching: find.byWidgetPredicate((w) => w is FilledButton)));
    expect(review.onPressed, isNull, reason: 'a hard-to-read value is still unconfirmed');
    expect(find.textContaining('1 value still needs your confirmation'), findsOneWidget);
    // Bank details (masked by the server) are not shown at all.
    expect(find.textContaining('[masked]'), findsNothing);
    expect(find.textContaining('Bank account'), findsNothing);

    await app.tap(find.byTooltip('Edit line 3'));
    expect(find.text('Edit line 3'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextFormField, 'Quantity'), '4');
    await app.tap(find.text('Save line'));
    final patch = backend.calls('PATCH /invoices/$standaloneId/lines/${clamp['id']}').single.body as Map;
    expect(patch, {'expected_version': clamp['version'], 'quantity': '4'});
    expect(backend.calls('POST /invoices/$standaloneId/explain'), hasLength(1), reason: 'sums recalculated by the server');
    expect(find.text('You corrected this'), findsWidgets);
    expect(find.text('Read as: 3'), findsOneWidget);
    expect(find.textContaining('4 × NZD 6.50 = NZD 26.00'), findsOneWidget);
    expect(find.text('Lines add up to: NZD 398.10'), findsOneWidget);
    expect(find.text('Difference: NZD 1.00'), findsOneWidget);
    expect(find.text('Needs your confirmation'), findsNothing);
    await app.stop();
  });

  testWidgets('confirming a line as printed sends no changes; a version conflict offers a reload', (tester) async {
    final (app, backend) = setUp(tester);
    final clamp = (extracted['lines'] as List).cast<Map>().singleWhere((l) => l['description'] == 'S/S hose clamp 316');
    backend.json('GET /invoices/$standaloneId', 200, extracted);
    backend.json('PATCH /invoices/$standaloneId/lines/${clamp['id']}', 409, inv('error_version_conflict'));
    await app.start();
    await app.go('/invoices/$standaloneId/review');
    await app.tap(find.text('Confirm line 3 as printed'));
    expect(backend.calls('PATCH /invoices/$standaloneId/lines/${clamp['id']}').single.body, {'expected_version': clamp['version']});
    expect(find.text('This invoice has changed'), findsOneWidget);
    final before = backend.calls('GET /invoices/$standaloneId').length;
    await app.tap(find.text('Reload'));
    expect(backend.calls('GET /invoices/$standaloneId').length, before + 1);
    await app.stop();
  });

  testWidgets('narrow phone layout stacks the document above the values', (tester) async {
    final (app, backend) = setUp(tester, size: const Size(400, 900));
    backend.json('GET /invoices/$standaloneId', 200, extracted);
    await app.start(size: const Size(400, 900));
    await app.go('/invoices/$standaloneId/review');
    expect(find.text('Invoice document (PDF · 1 page)'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await app.stop();
  });

  testWidgets('standalone explanation: comparison unavailable, sharing unavailable, no send button', (tester) async {
    final (app, backend) = setUp(tester);
    backend.json('GET /invoices/$standaloneId', 200, inv('invoice_standalone_explained'));
    backend.json('POST /invoices/$standaloneId/questions', 201, inv('question_draft'));
    await app.start();
    await app.go('/invoices/$standaloneId');
    expect(find.text('Comparison unavailable'), findsOneWidget);
    expect(find.textContaining('not linked to a service job, so there is no accepted scope'), findsOneWidget);
    expect(find.text('Sharing isn’t available for this invoice'), findsOneWidget);
    expect(find.text('What each line is'), findsOneWidget);
    expect(find.textContaining('hr: hour'), findsWidgets);
    expect(find.text('Does not add up'), findsOneWidget);
    expect(find.text('12 months on parts supplied'), findsOneWidget);
    expect(find.textContaining('does not judge whether prices are fair'), findsOneWidget);
    expect(find.text('Provisional until reviewed'), findsNothing, reason: 'the invoice was reviewed');
    // Suggested question → editable draft (nothing is sent).
    await app.tap(find.text('Edit and save'));
    expect(find.text('Edit the suggested question'), findsOneWidget);
    await app.tap(find.text('Save draft'));
    final body = backend.calls('POST /invoices/$standaloneId/questions').single.body as Map;
    expect(body['suggestion_key'], isNotNull);
    expect(find.textContaining('Send to the contractor'), findsNothing);
    expect(backend.requests.where((r) => r.path.endsWith('/send')), isEmpty);
    // Forbidden vocabulary never appears.
    for (final word in ['overcharg', 'fraud', 'unfair', 'Pay now', 'Dispute']) {
      expect(find.textContaining(word), findsNothing, reason: word);
    }
    await app.stop();
  });

  testWidgets('job-linked: matches, differences, “no approval record available”; explicit send with a chosen document',
      (tester) async {
    final (app, backend) = setUp(tester);
    final draft = (jobDraft['questions'] as List).cast<Map>().singleWhere((q) => q['status'] == 'draft');
    var current = jobDraft;
    backend.on('GET /invoices/$jobId', (_) => FakeResponse(200, current));
    backend.on('POST /invoices/$jobId/questions/${draft['id']}/send', (_) {
      current = invMap('invoice_job_question_sent');
      return FakeResponse(200, inv('question_sent'));
    });
    await app.start();
    await app.go('/invoices/$jobId');
    expect(find.text('Linked to a service job'), findsOneWidget);
    expect(find.text('Matches the accepted scope'), findsWidgets);
    expect(find.text('Differs from the accepted scope'), findsWidgets);
    expect(find.text('Additional — not in the accepted scope'), findsOneWidget);
    expect(find.textContaining('No approval record available'), findsOneWidget);
    expect(find.textContaining('Amount: invoice NZD 95.00 · accepted scope NZD 85.00'), findsOneWidget);
    expect(find.text('Draft — not sent'), findsOneWidget);
    expect(backend.requests.where((r) => r.path.endsWith('/send')), isEmpty, reason: 'never sent automatically');

    await app.tap(find.text('Send to the contractor…'));
    expect(find.text('Send this question?'), findsOneWidget);
    await app.tap(find.byType(CheckboxListTile));
    await app.tap(find.text('Send'));
    final send = backend.calls('POST /invoices/$jobId/questions/${draft['id']}/send').single;
    expect(send.headers['Idempotency-Key'], isNotNull);
    expect(send.body, {'expected_version': draft['version'], 'asset_ids': [jobAssetId]});
    expect(find.text('Sent — waiting for a reply'), findsOneWidget);
    await app.stop();
  });

  testWidgets('the attributed contractor reply and the corrected revision', (tester) async {
    final (app, backend) = setUp(tester);
    final detail = invMap('invoice_with_response');
    backend.json('GET /invoices/${detail['id']}', 200, detail);
    await app.start();
    await app.go('/invoices/${detail['id']}');
    expect(find.text('Answered'), findsOneWidget);
    expect(find.textContaining('Reply from the assigned contractor'), findsOneWidget);
    expect(find.textContaining('the sundries were not agreed'), findsOneWidget);
    expect(find.textContaining('Attached a corrected invoice — revision 2'), findsOneWidget);
    expect(find.text('A corrected invoice was attached'), findsOneWidget);
    expect(find.text('Read this document'), findsOneWidget);
    expect(find.text('Revision 2 (current)'), findsOneWidget);
    expect(find.textContaining('Corrected invoice from the contractor'), findsWidgets);
    await app.stop();
  });

  testWidgets('unreadable image and unavailable reading are honest; manual entry stays available', (tester) async {
    final (app, backend) = setUp(tester);
    final image = invMap('invoice_image_unreadable');
    backend.json('GET /invoices/${image['id']}', 200, image);
    // The real "not read yet" invoice with the availability flag the server
    // sends when extraction is disabled (SERVICE_INVOICE_EXTRACTION_PROVIDER=disabled).
    final unavailable = copyOf(invMap('invoice_created'));
    (unavailable['extraction'] as Map)
      ..['available'] = false
      ..['provider'] = 'disabled'
      ..['substitute'] = false
      ..['message'] = 'Automatic invoice reading is unavailable right now. You can enter and correct the details yourself.';
    backend.json('GET /invoices/${unavailable['id']}', 200, unavailable);
    await app.start();
    await app.go('/invoices/${image['id']}');
    expect(find.text('This document couldn’t be read automatically'), findsOneWidget);
    expect(find.text('Enter the details'), findsOneWidget);
    await app.go('/invoices/${unavailable['id']}');
    expect(find.text('Automatic reading is unavailable'), findsOneWidget);
    expect(find.text('Read this document'), findsNothing);
    expect(find.text('Enter the details'), findsOneWidget);
    await app.stop();
  });

  testWidgets('someone else’s invoice is not found (no retry loop)', (tester) async {
    final (app, backend) = setUp(tester);
    backend.json('GET /invoices/$standaloneId', 404, inv('error_invoice_not_found'));
    await app.start();
    await app.go('/invoices/$standaloneId');
    expect(find.text('Invoice not found'), findsWidgets);
    expect(find.text('Try again'), findsNothing);
    await app.stop();
  });

  testWidgets('delete asks first, then sends the expected version', (tester) async {
    final (app, backend) = setUp(tester);
    backend.json('GET /invoices/$standaloneId', 200, extracted);
    backend.json('DELETE /invoices/$standaloneId', 204, null);
    backend.json('GET /invoices', 200, inv('invoice_list_empty'));
    await app.start();
    await app.go('/invoices/$standaloneId');
    await app.tap(find.byTooltip('Delete invoice'));
    expect(find.text('Delete this invoice?'), findsOneWidget);
    await app.tap(find.text('Delete invoice'));
    expect(backend.calls('DELETE /invoices/$standaloneId').single.query, {'expected_version': '${extracted['version']}'});
    expect(app.location, '/invoices');
    await app.stop();
  });
}
