// Contractor journeys in the real app shell, fed with captured server payloads:
// inbox, organisation admin acceptance with member choice, and the assigned job.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../service_jobs/sj_test_helpers.dart';

void main() {
  final p = '/service-jobs/$jobId';

  testWidgets('inbox: organisations, invitations for admins and assigned jobs', (tester) async {
    final backend = contractorBackend();
    backend.json('GET /contractors/me/jobs', 200, sj('contractor_inbox_invited'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/inbox');
    final me = sjList('contractor_me');
    final inv = (sjMap('contractor_inbox_invited')['invitations'] as List).first as Map;
    for (final m in me) {
      expect(find.text(m['name'] as String), findsOneWidget);
    }
    expect(find.text('Invitations to review'), findsOneWidget);
    expect(find.text(inv['job_title'] as String), findsOneWidget);
    expect(find.textContaining('Stabicraft 2050 Supercab'), findsOneWidget);
    expect(find.text('No jobs assigned to you yet.'), findsOneWidget);
    expect(find.textContaining('issue'), findsNothing, reason: 'no job content in an invitation summary');
    await app.tap(find.text(inv['job_title'] as String));
    expect(app.location, '/contractor/organizations/${inv['organization_id']}');
  });

  testWidgets('org admin accepts an invitation and chooses who works it', (tester) async {
    final backend = contractorBackend();
    final inv = sjList('org_invitations').first;
    final org = inv['organization_id'] as String;
    final technician = sjList('org_members').firstWhere((m) => m['role'] == 'member');
    backend.json('GET /contractors/organizations/$org/invitations', 200, [inv]);
    backend.json('GET /contractors/organizations/$org/members', 200, sj('org_members'));
    backend.json('POST /contractors/assignments/${inv['assignment_id']}/accept', 200, sj('invitation_accepted'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/organizations/$org');
    expect(find.text('Waiting for your answer'), findsOneWidget);
    expect(find.text('Access credentials and exact location'), findsOneWidget);
    await app.tapText('Accept and assign people');
    expect(find.text('Who will work this job?'), findsOneWidget);
    await app.tap(inDialog(technician['name'] as String));
    await app.tap(inDialog('Confirm'));
    expect(backend.calls('POST /contractors/assignments/${inv['assignment_id']}/accept').single.body, {
      'member_user_ids': [technician['user_id']],
    });
    expect(find.text('Invitation accepted'), findsOneWidget);
  });

  testWidgets('org admin declines an invitation', (tester) async {
    final backend = contractorBackend();
    final inv = sjList('org_invitations').first;
    final org = inv['organization_id'] as String;
    backend.json('GET /contractors/organizations/$org/invitations', 200, [inv]);
    backend.json('GET /contractors/organizations/$org/members', 200, sj('org_members'));
    backend.json('POST /contractors/assignments/${inv['assignment_id']}/decline', 200, sj('invitation_declined'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/organizations/$org');
    await app.tapText('Decline');
    await app.tap(inDialog('Decline'));
    expect(backend.calls('POST /contractors/assignments/${inv['assignment_id']}/decline'), hasLength(1));
  });

  testWidgets('assigned job: tabs follow the granted sections; read-only brief with gaps and limitations',
      (tester) async {
    final app = SjApp(tester, contractorBackend());
    await app.start('/contractor/jobs/$jobId');
    expect(find.widgetWithText(Tab, 'Brief'), findsOneWidget);
    expect(find.widgetWithText(Tab, 'Requests'), findsOneWidget);
    expect(find.widgetWithText(Tab, 'Overview'), findsNothing);
    expect(find.widgetWithText(Tab, 'Sharing'), findsNothing);
    expect(find.textContaining('Brief — revision'), findsOneWidget);
    expect(find.text('Gaps and open requests:'), findsOneWidget);
    expect(find.text('Limitations'), findsOneWidget);
    expect(find.text('Preview the brief'), findsNothing, reason: 'contractors cannot publish');
    expect(find.text('Westhaven Marina'), findsWidgets);
  });

  testWidgets('assigned job: request one more view from the brief', (tester) async {
    final backend = contractorBackend();
    final brief = sjList('briefs_contractor').last;
    backend.json('POST $p/briefs/${brief['id']}/acknowledgements', 201, sj('brief_ack_requested_view'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/brief');
    await app.tapText('Request one more view');
    await app.enter('What should the owner photograph?', 'Pump label without moving the pump');
    await app.enter('Why it helps', 'Confirms the model');
    await app.tap(inDialog('Send request'));
    final body = backend.calls('POST $p/briefs/${brief['id']}/acknowledgements').single.body as Map;
    expect(body['kind'], 'incomplete');
    expect((body['requested_view'] as Map)['prompt'], 'Pump label without moving the pump');
    expect((body['requested_view'] as Map)['category'], 'label');
  });

  testWidgets('assigned job: credentials appear only when authorised and asked for', (tester) async {
    final backend = contractorBackend();
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/brief');
    final viewer = (sjMap('job_contractor_view')['viewer'] as Map);
    if (viewer['restricted_access'] == true) {
      expect(backend.calls('GET $p/access/restricted'), isEmpty, reason: 'audited read only on request');
      await app.tapText('Show access credentials');
      expect(backend.calls('GET $p/access/restricted'), hasLength(1));
      expect(find.text('4321'), findsOneWidget);
    } else {
      expect(find.textContaining('has not authorised you'), findsOneWidget);
    }
  });

  testWidgets('assigned job: confirm a measurement with the method used', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p/measurements', 200, sj('measurements'));
    final m = sjList('measurements').firstWhere((x) => x['dimension'] == 'hose_internal_diameter');
    backend.json('POST $p/measurements/${m['id']}/confirm', 200, sj('measurement_confirmed'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/measurements');
    expect(find.text('Record a measurement'), findsNothing);
    await app.tapText('Confirm measurement');
    await app.tap(inDialog('Confirm'));
    expect(backend.calls('POST $p/measurements/${m['id']}/confirm').single.body, {'method': 'contractor_site'});
  });

  testWidgets('assigned job: confirm a preparation requirement with quantity and basis', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p/preparation-items', 200, sj('preparation_suggested'));
    final item = sjList('preparation_suggested').first;
    backend.json('POST $p/preparation-items/${item['id']}/confirm', 200, sj('preparation_item_confirmed'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/preparation');
    expect(find.text('Add to cart'), findsNothing, reason: 'a brief grants no purchasing authority');
    await app.tapText('Confirm requirement');
    await app.enter('Quantity (optional)', '2');
    await app.tap(inDialog('Confirm requirement'));
    expect(find.text('Say how you arrived at the quantity'), findsOneWidget);
    await app.enter('Basis for the quantity', 'One at each hose end');
    await app.tap(inDialog('Confirm requirement'));
    final body = backend.calls('POST $p/preparation-items/${item['id']}/confirm').single.body as Map;
    expect(body['expected_version'], item['version']);
    expect(body['quantity'], '2');
    expect(body['quantity_basis'], 'One at each hose end');
  });

  testWidgets('assigned job: propose a scope with estimate lines in minor units', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p/scopes', 200, []);
    backend.json('POST $p/scopes', 201, sj('scope_proposed'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/scope');
    expect(find.textContaining('Accept revision'), findsNothing);
    await app.tapText('Propose a scope');
    await app.enter('Summary of the work *', 'Replace the outlet hose');
    await app.enter('Tasks (one per line; end with “?” if it needs site inspection)', 'Replace hose\nInspect far end?');
    await app.enter('Line 1 description', 'Labour');
    await app.enter('Qty', '1.5');
    await app.enter('Unit', 'hour');
    await app.enter(r'Unit price $', '95');
    await app.tap(inDialog('Send to the owner'));
    final body = backend.calls('POST $p/scopes').single.body as Map;
    expect(body['estimate_lines'], [
      {'description': 'Labour', 'kind': 'labour', 'quantity': '1.5', 'unit': 'hour', 'unit_price_minor': 9500},
    ]);
    expect(body['currency'], 'NZD');
    expect(body['tasks'], [
      {'description': 'Replace hose', 'needs_site_inspection': false},
      {'description': 'Inspect far end', 'needs_site_inspection': true},
    ]);
  });

  testWidgets('assigned job: record attendance', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p', 200, sj('job_contractor_view'));
    backend.json('GET $p/visits', 200, []);
    backend.json('POST $p/visits', 201, sj('visit_attended'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId/visits');
    await app.tapText('Record a visit');
    await app.tap(inDialog('Record'));
    final call = backend.calls('POST $p/visits').single;
    expect((call.body as Map)['kind'], 'attended');
    expect(call.headers['Idempotency-Key'], startsWith('helm-visit-'));
  });

  testWidgets('assigned job: feedback stays blind — nothing about the owner’s review before reveal', (tester) async {
    final app = SjApp(tester, contractorBackend());
    await app.start('/contractor/jobs/$jobId/feedback');
    expect(find.textContaining('Your review of the owner'), findsOneWidget);
    expect(find.text('Their review of you'), findsNothing);
    expect(find.text('Accuracy of problem description and evidence'), findsOneWidget);
  });

  testWidgets('an unrelated user gets a plain not-found for the job', (tester) async {
    final backend = contractorBackend();
    backend.json('GET $p', 404, sj('error_outsider_job'));
    backend.json('GET /contractors/me', 200, sj('contractor_me_empty'));
    backend.json('GET /contractors/me/jobs', 200, sj('contractor_inbox_empty'));
    final app = SjApp(tester, backend);
    await app.start('/contractor/jobs/$jobId');
    expect(find.text('Not found, or not shared with you'), findsOneWidget);
    app.go('/contractor/inbox');
    await app.settle();
    expect(find.textContaining('You are not a member of a contractor organisation'), findsOneWidget);
  });
}
