// Shared set-up for the catalogue / garage / checklist widget tests: the app
// signed in as the fixture user, whose garage holds the captured "Kahawai"
// vessel (Yamaha F150, linked to the synthetic boat-database model year).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/app_harness.dart';
import '../../helpers/fakes.dart';

Map<String, dynamic> cat(String name) => fixtureMap('catalogue/$name');
List<dynamic> catList(String name) => fixture('catalogue/$name') as List;

/// The captured vessel the catalogue fixtures were evaluated against.
Map<String, dynamic> get kahawai => cat('vessel_linked');
String get kahawaiId => kahawai['id'] as String;

/// A backend for the fixture user with Kahawai as their (primary) vessel.
FakeBackend catalogueBackend() {
  final backend = fixtureBackend();
  backend.json('GET /vessels/', 200, [kahawai]);
  backend.json('GET /vessels/$kahawaiId', 200, kahawai);
  backend.json('GET /products/categories', 200, catList('product_categories'));
  backend.json('GET /products/brands', 200, catList('product_brands'));
  backend.on('GET /products/', (r) {
    if (r.query['compatible_only'] == 'true') return FakeResponse(200, cat('products_compatible'));
    if (r.query['vessel_id'] != null) return FakeResponse(200, cat('products_page_vessel'));
    return FakeResponse(200, cat('products_page'));
  });
  return backend;
}

Future<AppHarness> startApp(
  WidgetTester tester,
  FakeBackend backend, {
  Size size = const Size(1280, 1600),
  double textScale = 1.0,
}) async {
  final app = AppHarness(tester, gateway: fixtureGateway(), backend: backend);
  await app.start(size: size, textScale: textScale);
  expect(app.location, '/');
  return app;
}
