// The assigned contractor's side: only the questions the owner sent, with the
// chosen documents; an attributed reply with an optional corrected invoice
// uploaded as a job document.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';

import '../../helpers/fakes.dart';
import 'invoice_test_helpers.dart';

void main() {
  final shared = invList('contractor_questions');
  final q = shared.single;
  final jobId = q['job_id'] as String;
  final route = '/contractor/jobs/$jobId/invoice-questions';

  testWidgets('shows the sent question, its line and documents; replies with a corrected invoice', (tester) async {
    final (backend, gateway) = ownerSession();
    final intent = invMap('contractor_asset_intent');
    final assetId = (intent['asset'] as Map)['id'] as String;
    var current = shared;
    backend.on('GET /service-jobs/$jobId/invoice-questions', (_) => FakeResponse(200, current));
    backend.json('POST /service-jobs/$jobId/assets/intents', 201, intent);
    backend.json('PUT /service-assets/$assetId/content', 202, inv('contractor_asset_content_accepted'));
    backend.json('GET /service-assets/$assetId', 200, inv('contractor_asset_available'));
    backend.on('POST /service-jobs/$jobId/invoice-questions/${q['id']}/respond', (_) {
      current = [invMap('contractor_response')];
      return FakeResponse(201, inv('contractor_response'));
    });
    final app = InvoiceHarness(tester,
        backend: backend,
        gateway: gateway,
        overrides: [documentPickerProvider.overrideWithValue(() async => pickedPdf)]);
    await app.start();
    await app.go(route);
    expect(find.text(q['text'] as String), findsOneWidget);
    expect(find.textContaining('Line 5 · Consumables: Consumables / sundries'), findsOneWidget);
    expect(find.textContaining('amount 12.00'), findsOneWidget);
    expect(find.text('Invoice document (PDF, 1 page)'), findsOneWidget);
    expect(find.text('Waiting for your reply'), findsOneWidget);

    await app.tap(find.text('Send reply'));
    expect(find.text('Write a reply'), findsOneWidget, reason: 'an empty reply is refused locally');
    await tester.enterText(find.widgetWithText(TextFormField, 'Your reply to the owner'), 'Corrected invoice attached.');
    await app.tap(find.text('Attach a corrected invoice (optional)'));
    expect(find.text('harbour-invoice.pdf'), findsOneWidget);
    await app.tap(find.text('Send reply'));
    final intentCall = backend.calls('POST /service-jobs/$jobId/assets/intents').single;
    expect((intentCall.body as Map)['purpose'], 'job_document');
    expect(intentCall.headers['Idempotency-Key'], isNotNull);
    final respond = backend.calls('POST /service-jobs/$jobId/invoice-questions/${q['id']}/respond').single.body as Map;
    expect(respond, {'text': 'Corrected invoice attached.', 'corrected_asset_id': assetId});
    expect(find.text('Answered'), findsOneWidget);
    expect(find.textContaining('Reply from your organization'), findsOneWidget);
    expect(find.text('A corrected invoice was attached.'), findsOneWidget);
    await app.stop();
  });

  testWidgets('the owner (or anyone not assigned) is told the page is not for them', (tester) async {
    final (backend, gateway) = ownerSession();
    backend.json('GET /service-jobs/$jobId/invoice-questions', 403, inv('error_contractor_only'));
    final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
    await app.start();
    await app.go(route);
    expect(find.text('This page is for the contractor assigned to the job'), findsOneWidget);
    backend.json('GET /service-jobs/$jobId/invoice-questions', 404, inv('error_contractor_questions_not_found'));
    await app.go('/invoices');
    backend.json('GET /invoices', 200, inv('invoice_list_empty'));
    await app.go(route);
    expect(find.text('Job not found'), findsOneWidget);
    await app.stop();
  });
}
