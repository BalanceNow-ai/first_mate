// Invoice client hardening against REAL captured payloads
// (scripts/capture_api_fixtures_invoices.py): specific wording for every
// comparison-unavailable reason the server emits, one key per question send,
// "Load more" for the list, and server-relative document links.
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/widgets/document_viewer.dart';

import '../../helpers/fakes.dart';
import 'invoice_test_helpers.dart';

void main() {
  final jobDraft = invMap('invoice_job_with_draft');
  final invoiceId = jobDraft['id'] as String;
  final jobAssetId = (jobDraft['revision'] as Map)['source_asset_id'] as String;
  final fallback = comparisonUnavailableReasonText('a_reason_the_client_does_not_know');

  group('comparison-unavailable reasons', () {
    test('a missing invoice currency is unavailable with a specific reason (captured)', () {
      final c = InvoiceExplanation.fromJson(invMap('explanation_currency_unknown')).content;
      final item = c.comparison.items.single;
      expect(item.status, 'comparison_unavailable');
      expect(item.differences.where((d) => d.field == 'currency'), isEmpty, reason: 'never a currency "difference"');
      expect(item.unavailableReasons, contains('invoice_currency_unknown'));
      expect(comparisonUnavailableReasonText('invoice_currency_unknown'), contains('currency'));
    });

    test('every reason the server emits has its own wording', () {
      // The reason strings of backend/app/services/service_jobs/invoice_explain.py (_compare).
      for (final r in const [
        'line_arithmetic_cannot_compute',
        'invoice_currency_unknown',
        'approved_currency_unknown',
        'invoice_amount_unreadable',
        'invoice_amount_unknown',
        'approved_amount_unknown',
        'invoice_unit_price_unreadable',
        'invoice_quantity_unreadable',
      ]) {
        expect(comparisonUnavailableReasonText(r), isNot(fallback), reason: r);
      }
      expect(comparisonUnavailableReasonText('approved_currency_unknown'), contains('accepted scope'));
    });

    testWidgets('the owner reads why the line cannot be compared', (tester) async {
      final (backend, gateway) = ownerSession();
      backend.json('GET /service-assets/$jobAssetId', 200, inv('standalone_asset_available'));
      backend.json(
        'GET /invoices/$invoiceId',
        200,
        copyOf(jobDraft)..['explanation'] = copyOf(invMap('explanation_currency_unknown')),
      );
      final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
      await app.start();
      await app.go('/invoices/$invoiceId');
      expect(find.textContaining(comparisonUnavailableReasonText('invoice_currency_unknown')), findsOneWidget);
      expect(find.text('Matches the accepted scope'), findsNothing);
      await app.stop();
    });
  });

  testWidgets('a retried question send reuses its Idempotency-Key', (tester) async {
    final (backend, gateway) = ownerSession();
    backend.json('GET /service-assets/$jobAssetId', 200, inv('standalone_asset_available'));
    backend.json('GET /invoices/$invoiceId', 200, jobDraft);
    final draft = (jobDraft['questions'] as List).cast<Map>().singleWhere((q) => q['status'] == 'draft');
    final route = 'POST /invoices/$invoiceId/questions/${draft['id']}/send';
    var attempts = 0;
    backend.on(route, (_) {
      attempts++;
      return attempts == 1
          ? const FakeResponse(503, {'detail': 'Service unavailable', 'code': 'unavailable'})
          : FakeResponse(200, inv('question_sent'));
    });
    final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
    await app.start();
    await app.go('/invoices/$invoiceId');
    for (var i = 0; i < 2; i++) {
      await app.tap(find.text('Send to the contractor…'));
      await app.tap(find.text('Send'));
    }
    final keys = [for (final c in backend.calls(route)) c.headers['Idempotency-Key']];
    expect(keys, hasLength(2));
    expect(keys.toSet(), hasLength(1), reason: 'the same send, retried, is one action');
    await app.stop();
  });

  testWidgets('the invoice list loads more with limit/offset', (tester) async {
    final (backend, gateway) = ownerSession();
    final all = invList('invoice_list');
    backend.on('GET /invoices', (r) {
      final offset = int.parse('${r.query['offset'] ?? 0}');
      return FakeResponse(200, all.skip(offset).take(int.parse('${r.query['limit']}')).toList());
    });
    final app = InvoiceHarness(
      tester,
      backend: backend,
      gateway: gateway,
      overrides: [listPageSizeProvider.overrideWith((ref, list) => 2)],
    );
    await app.start();
    await app.go('/invoices');
    expect(find.text(all[2]['title'] as String), findsNothing);
    await app.tap(find.text('Load more invoices'));
    expect(backend.calls('GET /invoices').last.query, {'limit': '2', 'offset': '2'});
    expect(find.text(all[2]['title'] as String), findsOneWidget);
    expect(find.text('Load more invoices'), findsNothing);
    await app.stop();
  });

  group('server-relative document links (local storage) resolve against the API', () {
    final local = copyOf(invMap('download_url_derivative'))..['url'] = '/api/v1/service-assets/local-download?token=t1';

    testWidgets('fetching image bytes', (tester) async {
      final (backend, gateway) = ownerSession();
      backend.json('POST /service-assets/$jobAssetId/download-url', 200, local);
      final fetched = <String>[];
      final app = InvoiceHarness(
        tester,
        backend: backend,
        gateway: gateway,
        fetcher: (url) async {
          fetched.add(url);
          return Uint8List(0);
        },
      );
      await app.start();
      await tester.runAsync(() async {
        final sub = app.container.listen(documentImageBytesProvider(jobAssetId), (_, _) {});
        await app.container.read(documentImageBytesProvider(jobAssetId).future).timeout(const Duration(seconds: 10));
        sub.close();
      });
      expect(fetched, ['http://api.test/api/v1/service-assets/local-download?token=t1']);
      await app.stop();
    });

    testWidgets('opening the document', (tester) async {
      final (backend, gateway) = ownerSession();
      backend.json('GET /service-assets/$jobAssetId', 200, inv('standalone_asset_available'));
      backend.json('GET /invoices/$invoiceId', 200, jobDraft);
      backend.json('POST /service-assets/$jobAssetId/download-url', 200, local);
      final opened = <Uri>[];
      final app = InvoiceHarness(
        tester,
        backend: backend,
        gateway: gateway,
        overrides: [
          documentLinkOpenerProvider.overrideWithValue((uri) async {
            opened.add(uri);
            return true;
          }),
        ],
      );
      await app.start();
      await app.go('/invoices/$invoiceId/review');
      await app.tap(find.text('Open the document'));
      expect(opened, [Uri.parse('http://api.test/api/v1/service-assets/local-download?token=t1')]);
      await app.stop();
    });
  });
}
