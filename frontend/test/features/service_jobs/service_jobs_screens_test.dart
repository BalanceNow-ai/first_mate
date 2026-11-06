// Owner journeys in the real app shell, fed with captured server payloads.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/fakes.dart';
import '../products/catalogue_backend.dart' show kahawaiId;
import '../vessels/vessel_detail_screen_test.dart' show garageBackend, openDetail;
import 'sj_test_helpers.dart';

void main() {
  final p = '/service-jobs/$jobId';

  testWidgets('vessel detail offers "Get help with a problem" and "Understand an invoice"', (tester) async {
    final app = await openDetail(tester, garageBackend());
    await app.tap(find.text('Get help with a problem'));
    expect(app.location, '/service-jobs/new?vessel_id=$kahawaiId&entry=vessel');
    app.go('/vessels/$kahawaiId');
    await app.settle();
    await app.tap(find.text('Understand an invoice'));
    expect(app.location, '/invoices/new?vessel_id=$kahawaiId');
  });

  testWidgets('service jobs list shows status, outstanding requests and gaps; opens a job', (tester) async {
    final app = SjApp(tester, ownerBackend());
    await app.start('/service-jobs');
    final item = sjList('jobs_list').first;
    expect(find.text('Service jobs'), findsWidgets);
    expect(find.text(item['title'] as String), findsOneWidget);
    expect(find.textContaining('Contractor: invited'), findsOneWidget);
    expect(find.text('Contractor inbox'), findsNothing, reason: 'not a member of any organisation');
    await app.tap(find.text(item['title'] as String));
    expect(app.location, '/service-jobs/${item['id']}');
    expect(find.text('Carry on where you left off'), findsOneWidget);
  });

  testWidgets('new job reuses the chosen vessel and sends the entry point', (tester) async {
    final backend = ownerBackend();
    final vessels = (fixture('vessels_list') as List).cast<Map>();
    final vesselId = vessels.first['id'] as String;
    backend.json('POST /service-jobs/', 201, sj('job_created'));
    backend.json('GET /service-jobs/${sjMap('job_created')['id']}', 200, sj('job_created'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/new?vessel_id=$vesselId&entry=vessel');
    expect(find.textContaining('We will use the details saved for ${vessels.first['nickname']}'), findsOneWidget);
    await app.tap(find.text('Start service job'));
    expect(find.text('Give the job a short title'), findsOneWidget);
    expect(backend.calls('POST /service-jobs/'), isEmpty);
    await app.enter('Short title *', 'Water under the sink');
    await app.enter('Which equipment is affected?', 'Freshwater pump');
    await app.tap(find.text('Soon'));
    await app.tap(find.text('Start service job'));
    final body = backend.calls('POST /service-jobs/').single.body as Map;
    expect(body['vessel_id'], vesselId);
    expect(body['entry_point'], 'vessel');
    expect(body['urgency'], 'soon');
    expect(body['affected_equipment'], 'Freshwater pump');
    expect(app.location, '/service-jobs/${sjMap('job_created')['id']}');
  });

  testWidgets('overview: correct vessel context explicitly; a 409 asks to reload', (tester) async {
    final backend = ownerBackend(job: 'job_created');
    backend.json('PUT $p/vessel-context', 409, sj('error_version_conflict'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId');
    expect(find.text('Vessel details used for this job'), findsOneWidget);
    expect(find.textContaining('please confirm or correct'), findsOneWidget);
    await app.tap(find.text('These details are right'));
    expect(find.text('This changed while you were looking'), findsOneWidget);
    final before = backend.calls('GET $p').length;
    await app.tap(find.text('Reload'));
    expect(backend.calls('GET $p').length, greaterThan(before));
  });

  testWidgets('capture: the next request with its reason and safety note; "cannot safely get" records a gap',
      (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/evidence-requests/next', 200, sj('next_proposal'));
    backend.json('POST $p/evidence-requests/next', 200, sj('next_accepted'));
    final req = sjMap('next_accepted')['request'] as Map;
    backend.json('POST $p/evidence-requests/${req['id']}/unavailable', 200, sj('request_unavailable'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/capture');
    final proposal = sjMap('next_proposal')['proposal'] as Map;
    expect(find.text(proposal['prompt'] as String), findsWidgets);
    expect(find.text('Why this helps: ${proposal['reason']}'), findsOneWidget);
    expect(find.text(proposal['safety_note'] as String), findsOneWidget);
    expect(find.textContaining('Local test analyser'), findsOneWidget);

    await app.tap(find.text('I cannot safely get this'));
    expect(find.text('That is fine — leave it'), findsOneWidget);
    await app.tap(find.text('Record gap'));
    expect(backend.calls('POST $p/evidence-requests/next').single.query['key'], proposal['key']);
    final body = backend.calls('POST $p/evidence-requests/${req['id']}/unavailable').single.body as Map;
    expect(body['reason'], 'cannot_safely_access');
    expect(body['expected_version'], req['version']);
    expect(find.text('Gap recorded — the contractor will see it'), findsOneWidget);
  });

  testWidgets('capture: take photo → intent tied to the request → PUT → processed; assets show status and hints',
      (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/evidence-requests/next', 200, sj('next_accepted'));
    final intent = sjMap('asset_png_intent');
    final assetId = (intent['asset'] as Map)['id'];
    backend.json('POST $p/assets/intents', 201, intent);
    backend.json('PUT /service-assets/$assetId/content', 202, sj('asset_png_received'));
    backend.json('GET /service-assets/$assetId', 200, sj('asset_png_processed'));
    backend.json('POST /service-assets/$assetId/download-url', 200, sj('download_url'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/capture');

    await app.tap(find.text('Take photo'));
    expect(app.picker.calls, [true], reason: 'camera capture requested');
    final call = backend.calls('POST $p/assets/intents').single;
    expect((call.body as Map)['evidence_request_id'], (sjMap('next_accepted')['request'] as Map)['id']);
    expect(backend.calls('PUT /service-assets/$assetId/content'), hasLength(1));
    expect(find.text('Photo added'), findsOneWidget);

    expect(find.text('Ready'), findsWidgets);
    expect(find.text('Rejected'), findsWidgets);
    expect(find.textContaining('not supported'), findsWidgets);
    expect(find.text('Framing: not assessed'), findsWidgets);
    expect(find.text('Label legibility: not assessed'), findsWidgets);
    await app.tap(find.text('Download'));
    expect(app.opener.opened.single.toString(), sjMap('download_url')['url']);
    expect(find.textContaining('helm-private'), findsNothing, reason: 'storage paths are never shown');
  });

  testWidgets('measurements: explicit dimension types and provenance badges; record one', (tester) async {
    final backend = ownerBackend();
    backend.json('POST $p/measurements', 201, sj('measurement_owner'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/measurements');
    expect(find.text('Pump outlet hose — Hose inside diameter (ID)'), findsOneWidget);
    expect(find.text('Pump outlet hose — Hose outside diameter (OD)'), findsNWidgets(2));
    expect(find.text('25 mm'), findsOneWidget);
    expect(find.text('Owner declared'), findsOneWidget);
    expect(find.text('Owner measured'), findsWidgets);
    expect(find.text('Superseded'), findsOneWidget);

    await app.tap(find.text('Record a measurement'));
    await app.tap(find.text('Save measurement'));
    expect(find.text('Choose the dimension type'), findsOneWidget);
    expect(backend.calls('POST $p/measurements'), isEmpty);
    await app.enter('What did you measure? *', 'Outlet hose');
    await app.tap(find.byType(DropdownButtonFormField<String>).at(0));
    await app.tap(find.text('Hose outside diameter (OD)').last);
    await app.enter('Value as measured or written *', '32');
    await app.tap(find.byType(DropdownButtonFormField<String>).at(1));
    await app.tap(find.text('Measured with a caliper').last);
    await app.tap(find.text('Save measurement'));
    final body = backend.calls('POST $p/measurements').single.body as Map;
    expect(body, {
      'dimension': 'hose_external_diameter',
      'component': 'Outlet hose',
      'value_text': '32',
      'unit': 'mm',
      'method': 'owner_caliper',
    });
  });

  testWidgets('preparation: provisional badges and unknowns; add to cart only on an explicit tap', (tester) async {
    final backend = ownerBackend();
    // The OWNER's view of the list after the contractor confirmed, asked and rejected.
    final items = sjList('preparation_items_owner_view');
    backend.json('GET $p/preparation-items', 200, items);
    backend.json('POST /cart/items', 201, fixture('cart_with_item'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/preparation');
    expect(find.textContaining('This list is provisional'), findsOneWidget);
    expect(find.text('Contractor confirmed'), findsWidgets);
    expect(find.text('Still unknown:'), findsWidgets);
    expect(find.text('Confirm requirement'), findsNothing, reason: 'owners do not confirm requirements');
    Finder card(String status) => find
        .ancestor(of: find.text(items.singleWhere((i) => i['status'] == status)['name'] as String), matching: find.byType(Card))
        .first;
    expect(find.descendant(of: card('rejected'), matching: find.text('Add to cart')), findsNothing,
        reason: 'never offered for a rejected item');
    expect(backend.calls('POST /cart/items'), isEmpty);
    final confirmed = items.singleWhere((i) => i['status'] == 'contractor_confirmed');
    await app.tap(find.descendant(of: card('contractor_confirmed'), matching: find.text('Add to cart')));
    expect(backend.calls('POST /cart/items'), hasLength(1));
    expect((backend.calls('POST /cart/items').single.body as Map)['product_id'],
        ((confirmed['candidates'] as List).first as Map)['product_id']);
    expect(find.textContaining('to your cart'), findsOneWidget);
  });

  testWidgets('sharing: choose an organisation and sections, preview exactly, then invite', (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/assignments', 200, []);
    backend.json('POST $p/assignments/preview', 200, sj('sharing_preview'));
    backend.json('POST $p/assignments', 201, sj('assignment_invited'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/sharing');
    final org = sjList('directory').first;
    expect(find.text('Send invitation'), findsNothing);
    await app.tap(find.textContaining(org['name'] as String));
    await app.tap(find.text('Access credentials and exact location'));
    await app.tap(find.text('Preview what they will see'));
    final previewBody = backend.calls('POST $p/assignments/preview').single.body as Map;
    expect(previewBody['organization_id'], org['id']);
    expect(previewBody['sections'], contains('access_restricted'));
    expect(previewBody['sections'], isNot(contains('invoices')));
    expect(find.textContaining('Preview: what'), findsOneWidget);
    expect(find.textContaining('Shown only to the assigned members you individually authorise'), findsOneWidget);
    await app.tap(find.text('Send invitation'));
    final invite = backend.calls('POST $p/assignments').single;
    expect(invite.headers['Idempotency-Key'], startsWith('helm-invite-'));
    expect((invite.body as Map)['sections'], previewBody['sections']);
  });

  testWidgets('sharing: live assignment with per-member credential access and revoke', (tester) async {
    final backend = ownerBackend();
    final asg = sjMap('assignment_member_restricted');
    backend.json('GET $p/assignments', 200, [asg]);
    backend.json('POST $p/assignments/${asg['id']}/revoke', 200, sj('assignment_revoked'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/sharing');
    expect(find.text('Accepted'), findsWidgets);
    expect(find.text('May see gate codes, keys, contacts and exact location'), findsOneWidget);
    await app.tap(find.text('Revoke access'));
    await app.tap(inDialog('Revoke access'));
    expect(backend.calls('POST $p/assignments/${asg['id']}/revoke'), hasLength(1));
  });

  testWidgets('brief: preview the snapshot, then publish exactly that revision', (tester) async {
    final backend = ownerBackend();
    final preview = sjMap('brief_preview');
    backend.json('POST $p/briefs/preview', 201, preview);
    backend.json('POST $p/briefs/${preview['id']}/publish', 200, sj('brief_published'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/brief');
    await app.tap(find.text('Preview the brief'));
    expect(find.text('Preview — revision ${preview['revision_number']}'), findsOneWidget);
    expect(find.text('Limitations'), findsOneWidget);
    expect(find.textContaining('I cannot safely get this'), findsWidgets);
    await app.tap(find.text('Publish this revision'));
    await app.tap(inDialog('Publish'));
    expect(backend.calls('POST $p/briefs/${preview['id']}/publish').single.body, {'content_digest': preview['content_digest']});
  });

  testWidgets('scope: the owner accepts one exact revision with its digest and an Idempotency-Key', (tester) async {
    final backend = ownerBackend();
    final scope = sjMap('scope_proposed');
    backend.json('GET $p/scopes', 200, [scope]);
    backend.json('POST $p/scopes/${scope['id']}/decision', 201, sj('scope_decision_accepted'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/scope');
    expect(find.text(r'$185.00 NZD'), findsOneWidget);
    expect(find.text(r'$142.50'), findsOneWidget);
    expect(find.textContaining('needs site inspection'), findsOneWidget);
    expect(find.text('Propose a scope'), findsNothing);
    await app.tap(find.text('Accept revision 1'));
    expect(find.textContaining('applies to revision 1 exactly as shown'), findsOneWidget);
    await app.tap(find.text('Accept this revision'));
    final call = backend.calls('POST $p/scopes/${scope['id']}/decision').single;
    expect(call.headers['Idempotency-Key'], startsWith('helm-scope-'));
    expect((call.body as Map)['revision_digest'], scope['content_digest']);
    expect((call.body as Map)['decision'], 'accepted');
  });

  testWidgets('visits: the owner can contest the contractor’s completion record', (tester) async {
    final backend = ownerBackend(job: 'job_completed_owner');
    final done = sjList('visits').last;
    backend.json('POST $p/visits/${done['id']}/contest', 201, sj('visit_contested'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/visits');
    expect(find.text('Work completed'), findsOneWidget);
    expect(find.text('Contractor attended'), findsWidgets);
    expect(find.text('Record a visit'), findsNothing, reason: 'the job is completed');
    await app.tap(find.text('Contest').first);
    await app.enter('What is wrong with it?', 'The fitting still drips');
    await app.tap(inDialog('Contest'));
    expect(backend.calls('POST $p/visits/${done['id']}/contest').single.headers['Idempotency-Key'], startsWith('helm-contest-'));
  });

  testWidgets('feedback: no default rating; N/A is explicit; blind until reveal', (tester) async {
    final backend = ownerBackend();
    backend.json('PUT $p/feedback/owner_to_contractor', 200, sj('feedback_owner_draft'));
    backend.json('POST $p/feedback/owner_to_contractor/submit', 201, sj('feedback_owner_submitted'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/feedback');
    final chips = tester.widgetList<ChoiceChip>(find.byType(ChoiceChip));
    expect(chips, isNotEmpty);
    expect(chips.where((c) => c.selected), isEmpty, reason: 'never a default rating');
    expect(find.textContaining('Reviews stay hidden until both of you submit'), findsOneWidget);
    await app.tap(find.text('5 · Excellent').first);
    await app.tap(find.text('Not applicable').last);
    await app.tap(find.text('Submit review'));
    expect(find.textContaining('3 question(s) are unanswered'), findsOneWidget);
    await app.tap(inDialog('Submit review'));
    final draft = backend.calls('PUT $p/feedback/owner_to_contractor').single.body as Map;
    expect(draft['ratings'], {'communication_clarity': 5, 'invoice_clarity_and_scope_relationship': 'not_applicable'});
    expect(backend.calls('POST $p/feedback/owner_to_contractor/submit'), hasLength(1));
  });

  testWidgets('feedback: revealed reviews show both sides; respond and report', (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p/feedback', 200, sj('feedback_owner_revealed'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId/feedback');
    expect(find.text('Your review'), findsOneWidget);
    expect(find.text('Their review of you'), findsOneWidget);
    expect(find.text('Not applicable'), findsWidgets);
    expect(find.text('Respond'), findsOneWidget);
    expect(find.text('Report'), findsOneWidget);
  });

  testWidgets('a job that is not shared with you shows a plain 404 message', (tester) async {
    final backend = ownerBackend();
    backend.json('GET $p', 404, sj('error_outsider_job'));
    final app = SjApp(tester, backend);
    await app.start('/service-jobs/$jobId');
    expect(find.text('Not found, or not shared with you'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('profile lists Service jobs, and the Contractor inbox only for organisation members', (tester) async {
    final backend = ownerBackend();
    final app = SjApp(tester, backend);
    await app.start('/profile');
    expect(find.text('Service jobs'), findsOneWidget);
    expect(find.text('Contractor inbox'), findsNothing);

  });

  testWidgets('profile shows the Contractor inbox for organisation members', (tester) async {
    final app = SjApp(tester, contractorBackend());
    await app.start('/profile');
    expect(find.text('Contractor inbox'), findsOneWidget);
    await app.tap(find.text('Contractor inbox'));
    expect(app.location, '/contractor/inbox');
  });
}
