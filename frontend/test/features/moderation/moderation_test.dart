// Moderation console against REAL captured payloads (a reported contractor
// review that included a gate code): models, role-gated entry, case queue,
// case detail with reported content, mandatory reason + disposition, audit trail.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/features/moderation/data/moderation_models.dart';

import '../../helpers/fakes.dart';
import '../invoices/invoice_test_helpers.dart';

void main() {
  final detail = invMap('moderation_case_detail');
  final caseId = detail['id'] as String;

  group('contract', () {
    test('case queue, detail, actions and resolution', () {
      final active = [for (final j in invList('moderation_cases_active')) CaseSummary.fromJson(j)];
      expect(active.every((c) => !c.resolved), isTrue);
      expect(active.map((c) => c.id), contains(caseId));
      final c = CaseDetail.fromJson(detail);
      expect(c.summary.subject, 'Reported review');
      expect(c.summary.category, 'personal_or_security_information');
      expect(c.summary.restrictContent, isTrue);
      expect(c.reason, contains('gate code'));
      expect(c.feedback!.direction, 'contractor_to_owner');
      expect(c.feedback!.contentState, 'under_review', reason: 'restricted while investigated');
      expect(c.reportedContent!.version, 1);
      expect(c.reportedContent!.ratings, {'problem_description_accuracy': '2 of 5'});
      expect(c.job.organizationName, isNotNull);
      expect(c.actions.single.action, 'reported');
      final assigned = CaseDetail.fromJson(invMap('moderation_case_assigned'));
      expect(assigned.summary.status, 'under_review');
      expect(assigned.summary.assignedModeratorId, isNotNull);
      final resolved = CaseDetail.fromJson(invMap('moderation_case_resolved'));
      expect(resolved.summary.resolved, isTrue);
      expect(resolved.summary.disposition, 'content_removed_for_personal_information');
      expect(resolved.dispositionNote, contains('gate code'));
      expect(resolved.feedback!.contentState, 'removed');
      expect(resolved.actions.map((a) => auditActionLabel(a.action)),
          ['Reported', 'Assigned', 'Resolved — Content removed (personal or security information)']);
      expect(resolved.actions.every((a) => a.reason.isNotEmpty), isTrue);
      final done = [for (final j in invList('moderation_cases_resolved')) CaseSummary.fromJson(j)];
      expect(done.every((c) => c.resolved), isTrue);
      expect(ApiError.fromResponse(422, inv('error_disposition_required')).code, 'disposition_required');
      expect(ApiError.fromResponse(409, inv('error_case_resolved')).code, 'case_resolved');
      expect(ApiError.fromResponse(403, inv('error_moderation_forbidden')).code, 'forbidden');
    });

    test('the moderator role comes from /auth/me', () {
      expect(moderatorRoles.contains(invMap('auth_me_moderator')['role']), isTrue);
      expect(moderatorRoles.contains(invMap('auth_me_owner')['role']), isFalse);
    });
  });

  testWidgets('owners see no moderation entry and the console refuses them', (tester) async {
    final (backend, gateway) = ownerSession();
    final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
    await app.start();
    await app.go('/profile');
    expect(find.text('Moderation'), findsNothing);
    await app.go('/moderation');
    expect(find.text('Moderation is only available to moderators.'), findsOneWidget);
    expect(backend.calls('GET /moderation/cases'), isEmpty);
    await app.stop();
  });

  testWidgets('moderator: filter, open a case, resolve with a disposition and a reason', (tester) async {
    final (backend, gateway) = moderatorSession();
    backend.on('GET /moderation/cases', (r) => FakeResponse(
        200, r.query['status'] == 'resolved' ? inv('moderation_cases_resolved') : inv('moderation_cases_active')));
    var current = detail;
    backend.on('GET /moderation/cases/$caseId', (_) => FakeResponse(200, current));
    backend.on('POST /moderation/cases/$caseId/actions', (r) {
      current = invMap('moderation_case_resolved');
      return FakeResponse(200, current);
    });
    final app = InvoiceHarness(tester, backend: backend, gateway: gateway);
    await app.start();
    await app.go('/profile');
    await app.tap(find.text('Moderation'));
    expect(app.location, '/moderation');
    expect(backend.calls('GET /moderation/cases').last.query['status'], 'active');
    await app.tap(find.widgetWithText(ChoiceChip, 'Resolved'));
    expect(backend.calls('GET /moderation/cases').last.query['status'], 'resolved');
    await app.tap(find.widgetWithText(ChoiceChip, 'Active'));

    await app.go('/moderation/cases/$caseId');
    expect(find.text('Reported review: Personal or security information'), findsOneWidget);
    expect(find.textContaining('Their reason: The review includes my marina gate code.'), findsOneWidget);
    expect(find.text('Contractor’s review of the owner'), findsOneWidget);
    expect(find.text('Problem description accuracy: 2 of 5'), findsOneWidget);
    expect(find.text('Water under the sink when the pump runs'), findsOneWidget);
    expect(find.text('Reported'), findsOneWidget);

    // Reason and disposition are mandatory before anything is sent.
    await app.tap(find.text('Resolve case'));
    expect(find.text('Choose a disposition'), findsOneWidget);
    expect(find.text('Give a reason (at least 3 characters)'), findsOneWidget);
    expect(backend.calls('POST /moderation/cases/$caseId/actions'), isEmpty);

    await app.tap(find.byType(DropdownButtonFormField<String>).last);
    await app.tap(find.text('Content removed (personal or security information)').last);
    await tester.enterText(find.widgetWithText(TextFormField, 'Reason (required)'), 'Gate code removed; the rest stands.');
    await app.tap(find.text('Resolve case'));
    final body = backend.calls('POST /moderation/cases/$caseId/actions').single.body as Map;
    expect(body, {
      'action': 'resolve',
      'reason': 'Gate code removed; the rest stands.',
      'disposition': 'content_removed_for_personal_information',
    });
    expect(find.text('Resolved'), findsWidgets);
    expect(find.text('Take an action'), findsNothing, reason: 'a resolved case takes no further actions');
    expect(find.text('Resolved — Content removed (personal or security information)'), findsOneWidget);
    await app.stop();
  });
}
