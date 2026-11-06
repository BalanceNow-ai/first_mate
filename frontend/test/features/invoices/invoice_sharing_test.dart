// A line that can't be compared, and sending a question when the invoices section
// isn't shared with the contractor — from captured payloads.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';

import '../../helpers/fakes.dart';
import 'invoice_test_helpers.dart';

void main() {
  final jobDraft = invMap('invoice_job_with_draft');
  final invoiceId = jobDraft['id'] as String;
  final serviceJobId = jobDraft['job_id'] as String;
  final jobAssetId = (jobDraft['revision'] as Map)['source_asset_id'] as String;

  (InvoiceHarness, FakeBackend) setUp(WidgetTester tester, Map<String, dynamic> detail) {
    final (backend, gateway) = ownerSession();
    backend.json('GET /service-assets/$jobAssetId', 200, inv('standalone_asset_available'));
    backend.json('GET /invoices/$invoiceId', 200, detail);
    return (InvoiceHarness(tester, backend: backend, gateway: gateway), backend);
  }

  testWidgets('a line that cannot be compared says why and is not shown as a match', (tester) async {
    final detail = copyOf(jobDraft)..['explanation'] = copyOf(invMap('explanation_comparison_unavailable'));
    final (app, _) = setUp(tester, detail);
    await app.start();
    await app.go('/invoices/$invoiceId');
    expect(find.text('Can’t compare — a value is missing or unreadable'), findsOneWidget);
    expect(find.textContaining('not counted as a match'), findsOneWidget);
    expect(find.textContaining(comparisonUnavailableReasonText('invoice_amount_unknown')), findsOneWidget);
    expect(find.textContaining(comparisonUnavailableReasonText('line_arithmetic_cannot_compute')), findsOneWidget);
    expect(find.text('Matches the accepted scope'), findsNothing);
    expect(find.textContaining('because a value is missing or unreadable'), findsOneWidget,
        reason: 'the scope:unreadable suggested question');
    await app.stop();
  });

  testWidgets('sending without the invoices section explains it and offers to edit sharing', (tester) async {
    final (app, backend) = setUp(tester, jobDraft);
    final draft = (jobDraft['questions'] as List).cast<Map>().singleWhere((q) => q['status'] == 'draft');
    backend.json('POST /invoices/$invoiceId/questions/${draft['id']}/send', 409, inv('error_invoices_section_not_shared'));
    await app.start();
    await app.go('/invoices/$invoiceId');
    await app.tap(find.text('Send to the contractor…'));
    await app.tap(find.text('Send'));
    expect(backend.calls('POST /invoices/$invoiceId/questions/${draft['id']}/send'), hasLength(1));
    expect(find.text('Invoice questions aren’t shared with this contractor'), findsOneWidget);
    expect(find.textContaining('nothing has been sent'), findsOneWidget);
    expect(find.text('Draft — not sent'), findsOneWidget);
    await app.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Edit sharing')));
    expect(app.location, '/service-jobs/$serviceJobId/sharing');
    await app.stop();
  });

  testWidgets('a contractor without the invoices section is told the owner has not shared it', (tester) async {
    final (backend, gateway) = ownerSession();
    backend.json('GET /service-jobs/$serviceJobId/invoice-questions', 403, inv('error_contractor_section_not_shared'));
    final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
    await app.start();
    await app.go('/contractor/jobs/$serviceJobId/invoice-questions');
    expect(find.text('The owner hasn’t shared invoice questions on this job with you'), findsOneWidget);
    expect(find.text('Retry'), findsNothing);
    await app.stop();
  });
}
