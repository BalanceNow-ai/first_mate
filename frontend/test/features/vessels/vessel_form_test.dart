import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/fakes.dart';
import '../products/catalogue_backend.dart';

void main() {
  testWidgets('HIN decode shows a suggestion; nothing is applied until the user accepts it', (tester) async {
    final backend = catalogueBackend();
    backend.json('POST /boat-db/hin/decode', 200, cat('hin_decode_valid'));
    backend.json('POST /vessels/', 201, kahawai);
    final app = await startApp(tester, backend, size: const Size(900, 2600));
    app.go('/vessels/new');
    await app.settle();

    await app.enter('Nickname *', 'Kahawai');
    await app.enter('Make *', 'My own make');
    await app.enter('Year *', '2019');
    await app.enter('HIN (hull identification number)', 'nz-z9x12345c121');
    await app.tap(find.text('Decode HIN'));

    expect(backend.calls('POST /boat-db/hin/decode').single.body, {'hin': 'nz-z9x12345c121'});
    expect(find.text('HIN decoded'), findsOneWidget);
    expect(find.text('Synthetic Test Marine (fixture) (synthetic test data)'), findsOneWidget);
    expect(find.text('2021'), findsWidgets); // model year
    expect(find.text('Manufacturer code belongs to a synthetic test fixture'), findsOneWidget);
    // Not auto-applied:
    expect(find.widgetWithText(TextFormField, '2019'), findsOneWidget);
    expect(find.widgetWithText(TextFormField, 'My own make'), findsOneWidget);

    await app.tap(find.text('Use year 2021'));
    await app.tap(find.text('Use make Synthetic Test Marine (fixture)'));
    await app.tap(find.text('Use NZ-Z9X12345C121'));
    expect(find.widgetWithText(TextFormField, '2021'), findsOneWidget);

    await app.enter('Model *', 'Fixture 600 Runabout');
    await app.tap(find.widgetWithText(ElevatedButton, 'Add vessel'));
    final body = backend.calls('POST /vessels/').single.body as Map;
    expect(body['make'], 'Synthetic Test Marine (fixture)');
    expect(body['year'], 2021);
    expect(body['hin'], 'NZ-Z9X12345C121');
  });

  testWidgets('an invalid HIN offers the manual fallback; an unknown MIC names no manufacturer',
      (tester) async {
    final backend = catalogueBackend();
    backend.on('POST /boat-db/hin/decode', (r) {
      final hin = (r.body as Map)['hin'] as String;
      return FakeResponse(200, cat(hin.startsWith('SYN') ? 'hin_decode_unrecognised_mic' : 'hin_decode_invalid'));
    });
    final app = await startApp(tester, backend, size: const Size(900, 2600));
    app.go('/vessels/new');
    await app.settle();

    await app.enter('HIN (hull identification number)', 'not-a-hin');
    await app.tap(find.text('Decode HIN'));
    expect(find.text('HIN could not be decoded'), findsOneWidget);
    expect(find.text('Check the number, or enter your vessel details manually.'), findsOneWidget);
    expect(find.textContaining('A HIN has 12 characters'), findsOneWidget);

    await app.enter('HIN (hull identification number)', 'SYN12345F121');
    await app.tap(find.text('Decode HIN'));
    expect(find.text('HIN decoded'), findsOneWidget);
    expect(find.text('Not identified'), findsOneWidget);
    expect(find.textContaining('Use make'), findsNothing);
    expect(find.text('Use year 2021'), findsOneWidget);
  });

  testWidgets('decode failures show the server detail', (tester) async {
    final backend = catalogueBackend();
    backend.json('POST /boat-db/hin/decode', 429, {'detail': 'Too many requests', 'code': 'rate_limited'});
    final app = await startApp(tester, backend, size: const Size(900, 2600));
    app.go('/vessels/new');
    await app.settle();
    await app.tap(find.text('Decode HIN'));
    expect(find.text('Enter a HIN to decode'), findsOneWidget);
    await app.enter('HIN (hull identification number)', 'SYN12345F121');
    await app.tap(find.text('Decode HIN'));
    expect(find.text('Could not decode the HIN: Too many requests'), findsOneWidget);
  });

  testWidgets('make and model suggestions come from the boat database', (tester) async {
    final backend = catalogueBackend();
    final makers = catList('boat_manufacturers_search');
    final maker = makers.cast<Map>().firstWhere((m) => m['is_synthetic'] == true);
    backend.json('GET /boat-db/manufacturers', 200, makers);
    backend.json('GET /boat-db/manufacturers/${maker['id']}/models', 200, catList('boat_models'));
    final app = await startApp(tester, backend, size: const Size(900, 2600));
    app.go('/vessels/new');
    await app.settle();

    await app.enter('Make *', 'Fixture');
    await app.settle();
    expect(backend.calls('GET /boat-db/manufacturers').last.query['q'], 'Fixture');
    await app.tap(find.text(maker['name'] as String).last);
    await app.enter('Model *', 'Runabout');
    await app.settle();
    expect(backend.calls('GET /boat-db/manufacturers/${maker['id']}/models'), hasLength(1));
    await app.tap(find.text('Fixture 600 Runabout').last);
    expect(find.text('Boat database years: 2021, 2022, 2023'), findsOneWidget);
  });

  testWidgets('editing shows the stored HIN decode as a suggestion', (tester) async {
    final backend = catalogueBackend();
    final app = await startApp(tester, backend, size: const Size(900, 2600));
    app.go('/vessels/$kahawaiId/edit');
    await app.settle();
    expect(find.text('HIN decoded'), findsOneWidget);
    expect(find.text('Suggestion decoded from the HIN; it does not change the details you entered.'),
        findsOneWidget);
  });
}
