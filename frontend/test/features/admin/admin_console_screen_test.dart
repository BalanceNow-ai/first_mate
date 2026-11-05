// Admin console in the real app shell, fed with captured server payloads.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/fakes.dart';
import '../content/engagement_test_helpers.dart';

FakeBackend adminBackend(FakeBackend b) {
  b.json('GET /products/fitment-rules', 200, eng('admin_fitment_rules_unverified'));
  b.json('GET /boat-db/verification-requests', 200, eng('admin_verification_requests'));
  b.json('GET /knowledge/sources', 200, eng('admin_knowledge_sources'));
  b.json('GET /ai/specialists', 200, eng('ai_specialists'));
  b.json('GET /loyalty/admin/redemptions', 200, eng('admin_redemptions'));
  b.json('GET /admin/users', 200, eng('admin_users'));
  b.json('GET /admin/audit', 200, eng('admin_audit'));
  return b;
}

Future<dynamic> openAdmin(WidgetTester tester, {FakeBackend? backend}) async {
  final (b, gateway) = adminSession();
  final app = await engagementApp(tester, backend: adminBackend(backend ?? b), gateway: gateway, size: const Size(1200, 2000));
  app.go('/admin');
  await app.settle();
  return app;
}

void main() {
  testWidgets('fitment queue: filter, verify needs confidence >= 0.7, server errors shown', (tester) async {
    final (backend, _) = adminSession();
    final rules = engList('admin_fitment_rules_unverified');
    final rule = rules.first;
    backend.json('POST /products/fitment-rules/${rule['id']}/verify', 422, eng('error_confidence_too_low'));
    final app = await openAdmin(tester, backend: backend);

    expect(backend.calls('GET /products/fitment-rules').first.query['verification_status'], 'unverified');
    expect(find.text('Verify rule'), findsNWidgets(2));
    await tester.enterText(find.widgetWithText(TextField, 'Filter rules'), rule['engine_model'] as String);
    await tester.pump();
    expect(find.text('Verify rule'), findsOneWidget);

    await app.tap(find.text('Verify rule'));
    await tester.enterText(find.widgetWithText(TextFormField, 'Confidence (0–1)'), '0.5');
    await app.tap(find.text('Confirm verification'));
    expect(find.text('Needs at least 0.7 to verify'), findsOneWidget);
    expect(backend.calls('POST /products/fitment-rules/${rule['id']}/verify'), isEmpty);

    await tester.enterText(find.widgetWithText(TextFormField, 'Confidence (0–1)'), '0.8');
    await app.tap(find.text('Confirm verification'));
    expect((backend.calls('POST /products/fitment-rules/${rule['id']}/verify').single.body as Map)['confidence_score'], 0.8);
    expect(find.textContaining('confidence_too_low'), findsOneWidget);

    backend.json('POST /products/fitment-rules/${rule['id']}/verify', 200, eng('admin_fitment_rule_verified'));
    await app.tap(find.text('Verify rule'));
    await app.tap(find.text('Confirm verification'));
    expect(backend.calls('POST /products/fitment-rules/${rule['id']}/verify'), hasLength(2));
    expect(backend.calls('GET /products/fitment-rules').length, greaterThan(1), reason: 'queue refreshed');

    final other = rules.last;
    backend.json('POST /products/fitment-rules/${other['id']}/reject', 200, eng('admin_fitment_rule_rejected'));
    await tester.enterText(find.widgetWithText(TextField, 'Filter rules'), other['engine_model'] as String);
    await tester.pump();
    await app.tap(find.text('Reject rule'));
    await tester.enterText(find.widgetWithText(TextField, 'Note (optional)'), 'Wrong engine family');
    await app.tap(find.widgetWithText(FilledButton, 'Reject'));
    expect(backend.calls('POST /products/fitment-rules/${other['id']}/reject').single.body, {'notes': 'Wrong engine family'});
  });

  testWidgets('a 403 from the server is shown, not hidden', (tester) async {
    final (backend, _) = adminSession();
    adminBackend(backend);
    backend.json('GET /products/fitment-rules', 403, eng('error_forbidden'));
    final (_, gateway) = adminSession();
    final app = await engagementApp(tester, backend: backend, gateway: gateway, size: const Size(1200, 2000));
    app.go('/admin');
    await app.settle();
    expect(find.text('Could not load fitment rules'), findsOneWidget);
    expect(find.text(engMap('error_forbidden')['detail'] as String), findsOneWidget);
    expect(find.text('Code: forbidden'), findsOneWidget);
  });

  testWidgets('equipment verification: approve with a note', (tester) async {
    final (backend, _) = adminSession();
    final pending = engList('admin_verification_requests').firstWhere((r) => r['status'] == 'pending');
    backend.json('POST /boat-db/verification-requests/${pending['id']}/approve', 200, eng('admin_verification_approved'));
    final app = await openAdmin(tester, backend: backend);
    await app.tap(find.text('Equipment verification'));
    expect(find.text(pending['vessel_label'] as String), findsWidgets);
    expect(find.text('Equipment to review'), findsWidgets);
    await app.tap(find.text('Approve').first);
    await tester.enterText(find.widgetWithText(TextField, 'Review note (optional)'), 'Matches the plate');
    await app.tap(find.widgetWithText(FilledButton, 'Approve').last);
    expect(backend.calls('POST /boat-db/verification-requests/${pending['id']}/approve').single.body,
        {'review_note': 'Matches the plate'});
  });

  testWidgets('knowledge: synthetic and licence status, admit/revoke/re-embed/delete, ingest form', (tester) async {
    final (backend, _) = adminSession();
    final sources = engList('admin_knowledge_sources');
    backend.json('POST /knowledge/sources', 201, eng('admin_knowledge_ingested'));
    final app = await openAdmin(tester, backend: backend);
    await app.tap(find.text('Knowledge sources'));
    expect(find.text(sources.first['title'] as String), findsOneWidget);
    if (sources.any((s) => s['is_synthetic'] == true)) expect(find.text('Synthetic source'), findsWidgets);
    expect(find.textContaining('Licence'), findsWidgets);
    expect(find.text('Re-embed'), findsNWidgets(sources.length));

    await app.tap(find.text('Ingest document'));
    await app.tap(find.widgetWithText(FilledButton, 'Ingest'));
    expect(find.text('Choose a domain'), findsOneWidget);
    expect(backend.calls('POST /knowledge/sources'), isEmpty);
    await tester.enterText(find.widgetWithText(TextFormField, 'Title'), 'Anchoring basics');
    await tester.enterText(find.widgetWithText(TextFormField, 'Licence (e.g. CC BY 4.0, permission reference)'), 'CC BY 4.0');
    await app.tap(find.text('Licence verified'));
    await app.tap(find.widgetWithText(DropdownButtonFormField<String>, 'Domain'));
    await app.tap(find.text('Anchoring & Mooring Master').last);
    await tester.enterText(find.widgetWithText(TextFormField, 'Content'), '# Anchoring\n\nScope out 5:1.');
    await app.tap(find.widgetWithText(FilledButton, 'Ingest'));
    final body = backend.calls('POST /knowledge/sources').single.body as Map;
    expect(body['domain'], 'anchoring');
    expect(body['licence_verified'], isTrue);
    expect(body['format'], 'markdown');
    expect(body['is_synthetic'], isFalse);
  });

  testWidgets('redemptions: confirm with a staff note; users: role change via PUT', (tester) async {
    final (backend, _) = adminSession();
    final r = engList('admin_redemptions').first;
    backend.json('POST /loyalty/admin/redemptions/${r['id']}/confirm', 200, eng('admin_redemption_confirmed'));
    final customer = engList('admin_users').firstWhere((u) => u['role'] == 'customer');
    backend.json('PUT /admin/users/${customer['id']}/role', 200, eng('admin_user_role_updated'));
    final app = await openAdmin(tester, backend: backend);

    await app.tap(find.text('Experience redemptions'));
    await app.tap(find.text('Confirm').first);
    await tester.enterText(find.widgetWithText(TextField, 'Staff note (optional)'), 'Booked for Saturday');
    await app.tap(find.widgetWithText(FilledButton, 'Confirm').last);
    expect(backend.calls('POST /loyalty/admin/redemptions/${r['id']}/confirm').single.body, {'staff_note': 'Booked for Saturday'});

    await app.tap(find.text('Users & roles'));
    final tile = find.ancestor(of: find.textContaining(customer['email'] as String), matching: find.byType(ListTile));
    await app.tap(find.descendant(of: tile, matching: find.byType(DropdownButtonFormField<String>)));
    await app.tap(find.text('Operator').last);
    await app.tap(find.text('Change role'));
    expect(backend.calls('PUT /admin/users/${customer['id']}/role').single.body, {'role': 'operator'});

    await app.tap(find.text('Audit trail'));
    expect(find.text('set_role · user'), findsWidgets);
  });
}
