import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/app_harness.dart';
import '../../helpers/fakes.dart';
import 'catalogue_backend.dart';

/// Taps without scrolling (header controls are already on screen).
Future<void> tapInPlace(WidgetTester tester, AppHarness app, Finder finder) async {
  await tester.tap(finder);
  await app.settle();
}

void main() {
  testWidgets('evaluates fitment for the primary vessel; unknown is never "fits"', (tester) async {
    final app = await startApp(tester, catalogueBackend());
    app.go('/products');
    await app.settle();

    final request = app.backend.calls('GET /products/').last;
    expect(request.query['vessel_id'], kahawaiId);
    expect(request.query.containsKey('compatible_only'), isFalse);
    expect(request.query['limit'], '24');
    expect(find.textContaining('fitment checked against Kahawai'), findsOneWidget);
    expect(find.text('Fits Kahawai'), findsWidgets);
    expect(find.text('Does not fit'), findsWidgets);
    expect(find.text('Fit unknown — not verified'), findsWidgets);
  });

  testWidgets('"Compatible with" filter sends compatible_only, shows a banner and can be cleared',
      (tester) async {
    final app = await startApp(tester, catalogueBackend());
    app.go('/products');
    await app.settle();

    await tapInPlace(tester, app, find.text('Compatible with Kahawai only'));
    final request = app.backend.calls('GET /products/').last;
    expect(request.query['compatible_only'], 'true');
    expect(request.query['vessel_id'], kahawaiId);
    expect(find.textContaining('Compatible with Kahawai (2021'), findsOneWidget);
    expect(find.text('Does not fit'), findsNothing);
    expect(find.text('Fit unknown — not verified'), findsNothing);
    expect(find.text('Spark plug set — Yamaha F150 (synthetic)'), findsOneWidget);

    await tapInPlace(tester, app, find.text('Show all products'));
    expect(app.backend.calls('GET /products/').last.query.containsKey('compatible_only'), isFalse);
    expect(find.text('Compatible with Kahawai only'), findsOneWidget);
  });

  testWidgets('choosing "No vessel" stops fitment evaluation', (tester) async {
    final app = await startApp(tester, catalogueBackend());
    app.go('/products');
    await app.settle();
    await app.tap(find.byType(DropdownButtonFormField<String>));
    await app.tap(find.text('No vessel (browse everything)').last);
    final request = app.backend.calls('GET /products/').last;
    expect(request.query.containsKey('vessel_id'), isFalse);
    expect(find.text('Fits Kahawai'), findsNothing);
  });

  testWidgets('a deep link from a checklist applies part_role and compatible_only', (tester) async {
    final app = await startApp(tester, catalogueBackend());
    app.go('/products?part_role=spark_plug&compatible_only=true&vessel_id=$kahawaiId');
    await app.settle();
    final request = app.backend.calls('GET /products/').last;
    expect(request.query['part_role'], 'spark_plug');
    expect(request.query['compatible_only'], 'true');
    expect(request.query['vessel_id'], kahawaiId);
    expect(find.text('Part: Spark plug'), findsOneWidget);
  });

  testWidgets('text search uses /search/products and shows a fallback notice', (tester) async {
    final backend = catalogueBackend();
    backend.on('GET /search/products', (r) => FakeResponse(200, {
          ...cat('search_products'),
          // The server reports a Typesense failure like this (see SearchResponse).
          'engine': 'postgres_fallback',
          'notice': 'The search index is unavailable; showing database search results',
        }));
    final app = await startApp(tester, backend);
    app.go('/products');
    await app.settle();
    await tester.enterText(find.widgetWithText(TextField, 'Search parts and equipment'), 'plug');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await app.settle();

    final request = backend.calls('GET /search/products').single;
    expect(request.query['q'], 'plug');
    expect(request.query['vessel_id'], kahawaiId);
    expect(find.text('The search index is unavailable; showing database search results'), findsOneWidget);
    expect(find.text('Spark plug set — Yamaha F150 (synthetic)'), findsOneWidget);
  });

  testWidgets('loads the next page with offset and appends it', (tester) async {
    final backend = catalogueBackend();
    final first = cat('products_page');
    final second = cat('products_page2');
    backend.on('GET /products/', (r) {
      final offset = int.parse(r.query['offset'] as String);
      if (offset == 0) return FakeResponse(200, {...first, 'limit': 24});
      return FakeResponse(200, {...second, 'offset': offset, 'limit': 24});
    });
    final app = await startApp(tester, backend, size: const Size(1280, 4000));
    app.go('/products');
    await app.settle();
    final total = first['total'] as int;
    final firstCount = (first['items'] as List).length;
    expect(find.text('Showing $firstCount of $total'), findsOneWidget);

    await app.tap(find.text('Load more'));
    final calls = backend.calls('GET /products/');
    expect(calls.last.query['offset'], '$firstCount');
    final shown = firstCount + (second['items'] as List).length;
    expect(find.text('Showing $shown of $total'), findsOneWidget);
  });

  testWidgets('filters use the server query names', (tester) async {
    final app = await startApp(tester, catalogueBackend());
    app.go('/products');
    await app.settle();
    await tapInPlace(tester, app, find.widgetWithText(FilterChip, 'On sale'));
    await tapInPlace(tester, app, find.widgetWithText(FilterChip, 'In stock'));
    await tapInPlace(tester, app, find.text('Category'));
    await tapInPlace(tester, app, find.text('Engine Parts (14)').last);
    var q = app.backend.calls('GET /products/').last.query;
    expect(q['on_sale'], 'true');
    expect(q['in_stock'], 'true');
    expect(q['category'], 'Engine Parts');

    await tapInPlace(tester, app, find.text('Sub-category'));
    await tapInPlace(tester, app, find.text('Ignition (2)').last);
    await tapInPlace(tester, app, find.textContaining('Sort:'));
    await tapInPlace(tester, app, find.text('Price: low to high').last);
    q = app.backend.calls('GET /products/').last.query;
    expect(q['sub_category'], 'Ignition');
    expect(q['sort'], 'price_asc');

    await app.tap(find.text('Clear filters'));
    q = app.backend.calls('GET /products/').last.query;
    expect(q.keys, isNot(contains('category')));
    expect(q.keys, isNot(contains('on_sale')));
  });

  testWidgets('server errors show the detail and retry', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET /products/', 422, cat('error_vessel_required'));
    final app = await startApp(tester, backend);
    app.go('/products');
    await app.settle();
    expect(find.text('Could not load products'), findsOneWidget);
    expect(find.text('compatible_only requires vessel_id'), findsOneWidget);
    expect(find.text('Code: vessel_required'), findsOneWidget);
    backend.json('GET /products/', 200, cat('products_page_vessel'));
    await app.tap(find.text('Try again'));
    expect(find.text('Could not load products'), findsNothing);
  });

  testWidgets('large text and phone width do not overflow; controls are labelled', (tester) async {
    final handle = tester.ensureSemantics();
    final app = await startApp(tester, catalogueBackend(), size: const Size(400, 900), textScale: 2.0);
    app.go('/products');
    await app.settle();
    expect(tester.takeException(), isNull);
    await tapInPlace(tester, app, find.text('Compatible with Kahawai only'));
    expect(tester.takeException(), isNull);
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });
}
