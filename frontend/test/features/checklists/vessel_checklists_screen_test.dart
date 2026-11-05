import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/checklists/data/checklist_api.dart';
import 'package:helm_marine/features/checklists/export/export_saver.dart';
import 'package:helm_marine/features/checklists/providers/checklist_provider.dart';

import '../../helpers/app_harness.dart';
import '../../helpers/fakes.dart';
import '../products/catalogue_backend.dart';

String get _base => '/checklists/vessel/$kahawaiId';

Map<String, dynamic> get generated => cat('checklists_generated');

Map<String, dynamic> tierJson(Map<String, dynamic> set, String tier) =>
    ((set['tiers'] as List).cast<Map<String, dynamic>>()).firstWhere((t) => t['tier'] == tier);

List<Map<String, dynamic>> itemsOf(Map<String, dynamic> set, String tier) =>
    (tierJson(set, tier)['items'] as List).cast<Map<String, dynamic>>();

/// Records exports instead of opening browser tabs / writing files.
class FakeDeliverer extends ExportDeliverer {
  final List<ChecklistExport> delivered = [];
  final List<ExportFormat> opened = [];

  @override
  ExportTarget open(ExportFormat format) {
    opened.add(format);
    return ExportTarget.open(format);
  }

  @override
  Future<String> deliver(ChecklistExport export, ExportTarget target) async {
    delivered.add(export);
    return 'Opened ${export.filename}';
  }
}

/// The app harness with the export deliverer replaced.
class _Harness extends AppHarness {
  _Harness(super.tester, {required super.gateway, required super.backend, required ExportDeliverer deliverer})
      : _container = ProviderContainer(
          overrides: [
            ...testOverrides(gateway: gateway, backend: backend),
            exportDelivererProvider.overrideWithValue(deliverer),
          ],
          retry: (_, _) => null,
        );

  final ProviderContainer _container;

  @override
  ProviderContainer get container => _container;
}

Future<AppHarness> openChecklists(WidgetTester tester, FakeBackend backend,
    {FakeDeliverer? deliverer, Size size = const Size(1100, 2400)}) async {
  final app = _Harness(tester, gateway: fixtureGateway(), backend: backend, deliverer: deliverer ?? FakeDeliverer());
  await app.start(size: size);
  app.go('/vessels/$kahawaiId/checklists');
  await app.settle();
  return app;
}

void main() {
  testWidgets('not generated: disclaimer and generate', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, cat('checklists_not_generated'));
    backend.json('POST $_base/generate', 201, generated);
    final app = await openChecklists(tester, backend);

    expect(find.text('No checklists yet'), findsOneWidget);
    expect(find.textContaining('NOT a certified safety-equipment list'), findsOneWidget);
    await app.tap(find.text('Generate checklists'));
    expect(backend.calls('POST $_base/generate').single.query, isEmpty);
    expect(find.textContaining('NOT a certified safety-equipment list'), findsOneWidget);
    expect(find.text('Grab & Go Kit (day trips)'), findsOneWidget);
    expect(find.text('Day trips 0/11'), findsOneWidget);
    expect(find.text('Offshore 0/30'), findsOneWidget);
  });

  testWidgets('tiers show inherited items, fitment badges and unlinked search', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    final app = await openChecklists(tester, backend);

    final day = itemsOf(generated, 'grab_and_go');
    final plug = day.firstWhere((i) => i['part_role'] == 'spark_plug');
    expect(find.text(plug['item_name'] as String), findsOneWidget);
    expect(find.text((plug['product'] as Map)['name'] as String), findsOneWidget);
    expect(find.text('Fits Kahawai'), findsWidgets);
    expect(find.text('Fit unknown — not verified'), findsNothing);

    await app.tap(find.widgetWithText(Tab, 'Offshore 0/30'));
    expect(find.text('From Day trips kit'), findsWidgets);
    expect(find.text('From Coastal kit'), findsWidgets);

    await app.tap(find.widgetWithText(Tab, 'Day trips 0/11'));
    final unlinked = day.firstWhere((i) => i['link_status'] == 'unlinked');
    await app.tap(find.bySemanticsLabel('Find compatible part for ${unlinked['item_name']}'));
    expect(app.location,
        '/products?part_role=${unlinked['part_role']}&compatible_only=true&vessel_id=$kahawaiId');
  });

  testWidgets('ticking is optimistic, persisted via PATCH and rolled back on failure', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    final day = itemsOf(generated, 'grab_and_go');
    final item = cat('checklist_item_checked');
    final name = day.firstWhere((i) => i['id'] == item['id'])['item_name'] as String;
    backend.json('PATCH /checklists/items/${item['id']}', 200, item);
    final app = await openChecklists(tester, backend);

    await app.tap(find.bySemanticsLabel('On board: $name'));
    expect(backend.calls('PATCH /checklists/items/${item['id']}').single.body, {'is_checked': true});
    expect(find.text('Day trips 1/11'), findsOneWidget);
    expect(find.text('Coastal 1/20'), findsOneWidget, reason: 'shared by every tier that includes it');

    backend.json('PATCH /checklists/items/${item['id']}', 500, {'detail': 'Helm is having trouble', 'code': 'internal_error'});
    await app.tap(find.bySemanticsLabel('On board: $name'));
    expect(find.text('Day trips 1/11'), findsOneWidget, reason: 'rolled back');
    expect(find.textContaining('Could not update "$name": Helm is having trouble'), findsOneWidget);
  });

  testWidgets('add missing shows per-line results; a repeat adds nothing', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    var call = 0;
    backend.on('POST $_base/add-missing-to-cart', (r) {
      call++;
      return FakeResponse(200, cat(call == 1 ? 'checklist_add_missing_first' : 'checklist_add_missing_second'));
    });
    final app = await openChecklists(tester, backend);
    final first = cat('checklist_add_missing_first');

    await app.tap(find.text('Add missing to cart'));
    expect(backend.calls('POST $_base/add-missing-to-cart').single.body, {'tier': 'grab_and_go'});
    expect(find.text('Added ${first['added_count']} items to your cart'), findsOneWidget);
    expect(find.textContaining('Added · added'), findsWidgets);
    expect(find.text('Not added — no compatible product linked:'), findsOneWidget);
    expect(backend.calls('GET /cart/').length, greaterThanOrEqualTo(2), reason: 'cart refreshed');
    await app.tap(find.text('Close'));

    await app.tap(find.text('Add missing to cart'));
    expect(find.text('Nothing new added — your cart already covers these'), findsOneWidget);
    expect(find.textContaining('Already in cart'), findsWidgets);
  });

  testWidgets('manual link: a mismatch is refused, an unknown fit links with a warning', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    final unverified = cat('checklist_item_linked_unverified');
    final itemId = unverified['id'] as String;
    final page = cat('products_page_vessel');
    final products = (page['items'] as List).cast<Map<String, dynamic>>();
    final wrong = products.firstWhere((p) => p['sku'] == 'SYN-PLUG-140');
    final unknownProduct = unverified['product'] as Map<String, dynamic>;
    backend.on('PUT /checklists/items/$itemId/link', (r) {
      final id = (r.body as Map)['product_id'];
      return id == wrong['id']
          ? FakeResponse(409, cat('error_link_mismatch'))
          : FakeResponse(200, unverified);
    });
    // The server filters by part_role; serve the captured page filtered the same way.
    backend.on('GET /products/', (r) => FakeResponse(200, {
          ...page,
          'items': [
            for (final p in products)
              if (r.query['part_role'] == null || p['part_role'] == r.query['part_role']) p,
          ],
        }));
    final app = await openChecklists(tester, backend);

    await app.tap(find.bySemanticsLabel('Change product for Spare spark plugs'));
    final query = backend.calls('GET /products/').last.query;
    expect(query['part_role'], 'spark_plug');
    expect(query['vessel_id'], kahawaiId);
    expect(query.containsKey('compatible_only'), isFalse, reason: 'the owner may choose any part');

    await app.tap(find.bySemanticsLabel('Link ${wrong['name']}'));
    expect(find.textContaining('Not linked — Does not fit Kahawai'), findsOneWidget);

    await app.tap(find.text('Only spark plug parts'));
    expect(backend.calls('GET /products/').last.query.containsKey('part_role'), isFalse);
    final link = find.bySemanticsLabel('Link ${unknownProduct['name']}');
    await tester.ensureVisible(link); // scroll the dialog's list, then lay out
    await tester.pump();
    await app.tap(link);
    expect(find.text(unverified['warning'] as String), findsWidgets);
    expect(find.text('Chosen by you'), findsWidgets);
    expect(find.text('Fit unknown — not verified'), findsWidgets);
  });

  testWidgets('alternatives can be chosen', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    final day = itemsOf(generated, 'grab_and_go');
    final withAlt = day.firstWhere((i) => (i['alternatives'] as List).isNotEmpty);
    final alt = (withAlt['alternatives'] as List).first as Map;
    backend.json('PUT /checklists/items/${withAlt['id']}/link', 200, {
      ...withAlt,
      'product': alt,
      'alternatives': [withAlt['product']],
    });
    final app = await openChecklists(tester, backend);
    await app.tap(find.text('1 alternative'));
    await app.tap(find.bySemanticsLabel('Use ${alt['name']} for ${withAlt['item_name']}'));
    expect(backend.calls('PUT /checklists/items/${withAlt['id']}/link').single.body, {'product_id': alt['id']});
    expect(find.text('Linked ${alt['name']}'), findsOneWidget);
  });

  testWidgets('exports fetch with the token and hand the file to the platform', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    backend.on('GET $_base/export', (r) => FakeResponse(200, 'export:${r.query['tier']}:${r.query['format']}'));
    final deliverer = FakeDeliverer();
    final app = await openChecklists(tester, backend, deliverer: deliverer);

    await app.tap(find.text('Printable checklist'));
    final call = backend.calls('GET $_base/export').single;
    expect(call.query, {'tier': 'grab_and_go', 'format': 'html'});
    expect(call.authorization, 'Bearer token-a');
    expect(deliverer.opened, [ExportFormat.html]);
    expect(deliverer.delivered.single.mimeType, 'text/html');

    await app.tap(find.text('Download CSV'));
    expect(backend.calls('GET $_base/export').last.query['format'], 'csv');
    expect(deliverer.delivered.last.mimeType, 'text/csv');
  });

  testWidgets('regenerate confirms first; delete all returns to the empty state', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET $_base', 200, generated);
    backend.json('POST $_base/generate', 201, cat('checklists_regenerated'));
    backend.json('DELETE $_base', 204, null);
    final app = await openChecklists(tester, backend);

    await app.tap(find.byTooltip('Checklist options'));
    await app.tap(find.text('Regenerate checklists'));
    expect(find.text('Regenerate checklists?'), findsOneWidget);
    await app.tap(find.text('Cancel'));
    expect(backend.calls('POST $_base/generate'), isEmpty);

    await app.tap(find.byTooltip('Checklist options'));
    await app.tap(find.text('Regenerate checklists'));
    await app.tap(find.widgetWithText(TextButton, 'Regenerate'));
    expect(backend.calls('POST $_base/generate').single.query, {'regenerate': 'true'});

    backend.json('GET $_base', 200, cat('checklists_not_generated'));
    await app.tap(find.byTooltip('Checklist options'));
    await app.tap(find.text('Delete all checklists'));
    await app.tap(find.widgetWithText(TextButton, 'Delete'));
    expect(backend.calls('DELETE $_base'), hasLength(1));
    expect(find.text('No checklists yet'), findsOneWidget);
  });

  testWidgets('load errors show the server detail with retry; phone layout is labelled', (tester) async {
    final handle = tester.ensureSemantics();
    final backend = catalogueBackend();
    backend.json('GET $_base', 404, {'detail': 'Vessel not found', 'code': 'not_found'});
    final app = await openChecklists(tester, backend, size: const Size(400, 900));
    expect(find.text('Could not load checklists'), findsOneWidget);
    expect(find.text('Vessel not found'), findsOneWidget);
    backend.json('GET $_base', 200, generated);
    await app.tap(find.text('Try again'));
    expect(tester.takeException(), isNull);
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    handle.dispose();
  });
}
