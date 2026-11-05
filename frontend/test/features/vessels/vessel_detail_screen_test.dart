import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/app_harness.dart';
import '../../helpers/fakes.dart';
import '../products/catalogue_backend.dart';

FakeBackend garageBackend() {
  final backend = catalogueBackend();
  final v = kahawaiId;
  backend.json('GET /boat-db/model-years/${kahawai['model_year_id']}', 200, cat('boat_model_year_detail'));
  backend.json('GET /boat-db/equipment-categories', 200, catList('equipment_categories'));
  backend.json('GET /vessels/$v/equipment', 200, cat('equipment_list_factory'));
  backend.json('GET /vessels/$v/equipment/verification-requests', 200, []);
  backend.json('GET /vessels/$v/service-records', 200, catList('service_records'));
  backend.on('GET /vessels/$v/service-reminders', (r) =>
      FakeResponse(200, r.query['status'] == 'all' ? catList('reminders_all') : catList('reminders_active')));
  return backend;
}

Future<AppHarness> openDetail(WidgetTester tester, FakeBackend backend, {String? tab}) async {
  final app = await startApp(tester, backend, size: const Size(1000, 1800));
  app.go('/vessels/$kahawaiId');
  await app.settle();
  if (tab != null) await app.tap(find.widgetWithText(Tab, tab));
  return app;
}

void main() {
  testWidgets('overview shows the linked model year, HIN status and entry points', (tester) async {
    final app = await openDetail(tester, garageBackend());
    expect(find.text('Kahawai'), findsWidgets);
    expect(find.text('Synthetic Test Marine (fixture) Fixture 600 Runabout 2021'), findsOneWidget);
    expect(find.text('Synthetic test data — not a real boat model'), findsOneWidget);
    expect(find.text('NZ-Z9X12345C121 (valid)'), findsOneWidget);
    expect(find.text('HIN decoded'), findsOneWidget);
    expect(find.text('Voyage checklists'), findsOneWidget);
    expect(find.text('Ask First Mate'), findsOneWidget);
    await app.tap(find.text('Find compatible parts'));
    expect(app.location, '/products?vessel_id=$kahawaiId&compatible_only=true');
  });

  testWidgets('equipment: factory records are labelled unconfirmed and can be applied', (tester) async {
    final backend = garageBackend();
    backend.json('POST /vessels/$kahawaiId/equipment/apply-oem', 200, cat('equipment_apply_oem'));
    final app = await openDetail(tester, backend, tab: 'Equipment');

    expect(find.text('Installed equipment'), findsOneWidget);
    expect(find.textContaining('No installed equipment recorded yet'), findsOneWidget);
    expect(find.text('Factory equipment'), findsOneWidget);
    expect(find.text('Factory record (boat database)'), findsWidgets);
    expect(find.text('Unconfirmed'), findsWidgets);
    expect(find.text('Synthetic test data'), findsWidgets);
    expect(find.textContaining('not confirmed for your boat'), findsWidgets);
    expect(find.text('Verified'), findsNothing, reason: 'low-confidence OEM data is never presented as fact');

    final first = (cat('equipment_list_factory')['items'] as List).first as Map;
    await app.tap(find.bySemanticsLabel('Add ${first['make']} ${first['model']} to installed equipment'));
    expect(backend.calls('POST /vessels/$kahawaiId/equipment/apply-oem').single.body,
        {'oem_equipment_ids': [first['id']]});

    backend.json('GET /vessels/$kahawaiId/equipment', 200, cat('equipment_list_applied'));
    await app.tap(find.text('Add all factory equipment'));
    expect(backend.calls('POST /vessels/$kahawaiId/equipment/apply-oem').last.body, <String, dynamic>{});
    expect(find.textContaining('All factory equipment for this model year has been added'), findsOneWidget);
    expect(find.text('Added by you'), findsOneWidget);
    expect(find.text('Owner declared'), findsOneWidget);
  });

  testWidgets('equipment: add owner equipment with canonical fields', (tester) async {
    final backend = garageBackend();
    backend.json('POST /vessels/$kahawaiId/equipment', 201, cat('equipment_added'));
    final app = await openDetail(tester, backend, tab: 'Equipment');

    await app.tap(find.text('Add equipment'));
    await app.tap(find.text('Add')); // validation
    expect(find.text('Choose a category'), findsOneWidget);
    expect(find.text('Make is required'), findsOneWidget);

    await app.tap(find.widgetWithText(DropdownButtonFormField<String>, 'Category *'));
    await app.tap(find.text('Chartplotter / GPS').last);
    await app.enter('Make *', 'Garmin');
    await app.enter('Model', 'echoMAP UHD 93sv');
    await app.enter('Year', '2022');
    await app.enter('Installed on', '2022-10-01');
    await app.tap(find.text('Add'));
    expect(backend.calls('POST /vessels/$kahawaiId/equipment').single.body, {
      'category': 'chartplotter',
      'make': 'Garmin',
      'model': 'echoMAP UHD 93sv',
      'year': 2022,
      'installed_on': '2022-10-01',
    });
    expect(find.text('Equipment added'), findsOneWidget);
  });

  testWidgets('equipment: edit, remove and request verification', (tester) async {
    final backend = garageBackend();
    final applied = cat('equipment_list_applied');
    final owner = cat('equipment_added');
    backend.json('GET /vessels/$kahawaiId/equipment', 200, applied);
    backend.json('PATCH /vessels/$kahawaiId/equipment/${owner['id']}', 200, cat('equipment_updated'));
    backend.json('DELETE /vessels/$kahawaiId/equipment/${owner['id']}', 204, null);
    backend.json('POST /vessels/$kahawaiId/equipment/verification-requests', 201, cat('verification_request'));
    final app = await openDetail(tester, backend, tab: 'Equipment');

    await app.tap(find.byTooltip('Actions for Garmin echoMAP UHD 95sv'));
    await app.tap(find.text('Edit'));
    await app.enter('Serial number', 'GAR-002');
    await app.tap(find.text('Save'));
    final patch = backend.calls('PATCH /vessels/$kahawaiId/equipment/${owner['id']}').single.body as Map;
    expect(patch['serial_number'], 'GAR-002');
    expect(patch['category'], 'chartplotter');
    expect(patch.containsKey('notes'), isTrue, reason: 'cleared fields are sent as null');

    await app.tap(find.byTooltip('Actions for Garmin echoMAP UHD 95sv'));
    await app.tap(find.text('Remove'));
    await app.tap(find.widgetWithText(TextButton, 'Remove'));
    expect(backend.calls('DELETE /vessels/$kahawaiId/equipment/${owner['id']}'), hasLength(1));

    await app.tap(find.text('Request verification'));
    await app.enter('Note for the reviewer', 'Fitted at purchase');
    backend.json('GET /vessels/$kahawaiId/equipment/verification-requests', 200, catList('verification_requests'));
    await app.tap(find.text('Send request'));
    expect(backend.calls('POST /vessels/$kahawaiId/equipment/verification-requests').single.body,
        {'note': 'Fitted at purchase'});
    expect(find.textContaining('awaiting review'), findsOneWidget);
  });

  testWidgets('equipment: server errors are shown with retry', (tester) async {
    final backend = garageBackend();
    backend.json('GET /vessels/$kahawaiId/equipment', 404, {'detail': 'Vessel not found', 'code': 'not_found'});
    await openDetail(tester, backend, tab: 'Equipment');
    expect(find.text('Could not load equipment'), findsOneWidget);
    expect(find.text('Vessel not found'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('service: reminders, completion creates the next one, history from cents', (tester) async {
    final backend = garageBackend();
    final active = catList('reminders_active');
    final rem = cat('reminder_updated');
    backend.on('GET /vessels/$kahawaiId/service-reminders', (r) => FakeResponse(200, [rem]));
    backend.json('POST /vessels/$kahawaiId/service-reminders/${rem['id']}/complete', 200, cat('reminder_completed'));
    final app = await openDetail(tester, backend, tab: 'Service');
    expect(active, isNotEmpty);

    expect(find.text('Replace water pump impeller'), findsOneWidget);
    expect(find.text('Due 1 Oct 2026 or at 200 engine hours'), findsOneWidget);
    expect(find.text('Repeats every 12 months or every 100 hours'), findsOneWidget);
    expect(find.text('100-hour service'), findsOneWidget);
    expect(find.textContaining(r'$465.00'), findsOneWidget);

    await app.tap(find.bySemanticsLabel('Complete Replace water pump impeller'));
    await app.enter('Engine hours at completion', '130');
    await app.tap(find.widgetWithText(ElevatedButton, 'Complete'));
    final body = backend.calls('POST /vessels/$kahawaiId/service-reminders/${rem['id']}/complete').single.body as Map;
    expect(body['engine_hours'], 130);
    expect(body['record_service'], isTrue);
    expect(find.textContaining('Next: due 5 Nov 2027 or at 230 engine hours'), findsOneWidget);
  });

  testWidgets('service: add a reminder and a record (dollars sent as cents)', (tester) async {
    final backend = garageBackend();
    backend.json('POST /vessels/$kahawaiId/service-reminders', 201, cat('reminder_created'));
    backend.json('POST /vessels/$kahawaiId/service-records', 201, cat('service_record_created'));
    final app = await openDetail(tester, backend, tab: 'Service');

    await app.tap(find.text('Add reminder'));
    await app.enter('What needs doing *', 'Replace impeller');
    await app.tap(find.text('Save'));
    expect(find.text('Set a due date and/or due engine hours'), findsOneWidget);
    await app.enter('Due date', '2026-10-01');
    await app.enter('Repeat every (months)', '12');
    await app.tap(find.text('Save'));
    expect(backend.calls('POST /vessels/$kahawaiId/service-reminders').single.body,
        {'title': 'Replace impeller', 'due_on': '2026-10-01', 'interval_months': 12});

    await app.tap(find.text('Record a service'));
    await app.enter('Service *', '100-hour service');
    await app.enter('Performed on', '2026-09-14');
    await app.enter('Cost (NZD)', '450.5');
    await app.tap(find.text('Save'));
    final record = backend.calls('POST /vessels/$kahawaiId/service-records').single.body as Map;
    expect(record['cost_cents'], 45050);
    expect(record['performed_on'], '2026-09-14');
  });

  testWidgets('detail tabs meet tap-target and label guidelines', (tester) async {
    final handle = tester.ensureSemantics();
    final app = await openDetail(tester, garageBackend(), tab: 'Equipment');
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await app.tap(find.widgetWithText(Tab, 'Service'));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });
}
