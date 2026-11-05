// Pass-1 screens in the real app shell, fed with captured server payloads.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/app_harness.dart';
import '../helpers/fakes.dart';

Future<AppHarness> signedInApp(WidgetTester tester,
    {FakeBackend? backend, Size size = const Size(420, 900), double textScale = 1.0}) async {
  final app = AppHarness(tester, gateway: fixtureGateway(), backend: backend ?? fixtureBackend());
  await app.start(size: size, textScale: textScale);
  expect(app.location, '/');
  return app;
}

void main() {
  group('vessels', () {
    testWidgets('list and detail show canonical fields', (tester) async {
      final backend = fixtureBackend();
      final vessel = fixtureMap('vessel_create');
      backend.json('GET /vessels/${vessel['id']}', 200, vessel);
      final app = await signedInApp(tester, backend: backend);

      app.go('/vessels');
      await app.settle();
      expect(find.text('Sea Biscuit'), findsOneWidget);
      expect(find.text('Tender'), findsOneWidget);
      expect(find.text('Primary'), findsOneWidget);

      await app.tap(find.text('Sea Biscuit'));
      expect(app.location, '/vessels/${vessel['id']}');
      for (final text in ['Haines Hunter', 'SF600', '2018', 'Fibreglass', '19.5 ft', 'Outboard',
          'Mercury', 'F150', '420 h', '1B123456', 'NZ-HHB12345C818']) {
        expect(find.text(text), findsWidgets, reason: text);
      }
    });

    testWidgets('form requires nickname and year and posts canonical fields', (tester) async {
      final backend = fixtureBackend();
      backend.json('POST /vessels/', 201, fixture('vessel_create'));
      final app = await signedInApp(tester, backend: backend, size: const Size(600, 2400));
      app.go('/vessels/new');
      await app.settle();

      await app.tap(find.widgetWithText(ElevatedButton, 'Add vessel'));
      expect(find.text('Nickname is required'), findsOneWidget);
      expect(find.text('Year is required'), findsOneWidget);
      expect(backend.calls('POST /vessels/'), isEmpty);

      await app.enter('Nickname *', 'Sea Biscuit');
      await app.enter('Make *', 'Haines Hunter');
      await app.enter('Model *', 'SF600');
      await app.enter('Year *', '1800');
      await app.tap(find.widgetWithText(ElevatedButton, 'Add vessel'));
      expect(find.text('Year must be between 1900 and 2100'), findsOneWidget);

      await app.enter('Year *', '2018');
      await app.enter('Length (ft)', '19.5');
      await app.enter('Engine make', 'Mercury');
      await app.enter('Engine model', 'F150');
      await app.enter('Engine year', '2018');
      await app.enter('Engine hours', '420');
      await app.enter('HIN (hull identification number)', 'nz-hhb12345c818');
      await app.tap(find.widgetWithText(ElevatedButton, 'Add vessel'));

      final body = backend.calls('POST /vessels/').single.body as Map;
      expect(body, {
        'nickname': 'Sea Biscuit',
        'make': 'Haines Hunter',
        'model': 'SF600',
        'year': 2018,
        'is_primary': false,
        'hin': 'NZ-HHB12345C818',
        'length_ft': 19.5,
        'engine_make': 'Mercury',
        'engine_model': 'F150',
        'engine_year': 2018,
        'engine_hours': 420,
      });
      expect(app.location, '/vessels/${fixtureMap('vessel_create')['id']}');
    });

    testWidgets('server validation errors are shown on the form', (tester) async {
      final backend = fixtureBackend();
      backend.json('POST /vessels/', 422, {
        'detail': 'Request validation failed',
        'code': 'validation_error',
        'errors': [
          {'loc': ['body', 'hin'], 'msg': 'String should have at most 20 characters', 'type': 'string_too_long'},
        ],
      });
      final app = await signedInApp(tester, backend: backend, size: const Size(600, 2400));
      app.go('/vessels/new');
      await app.settle();
      await app.enter('Nickname *', 'Tender');
      await app.enter('Make *', 'Quintrex');
      await app.enter('Model *', '350 Dory');
      await app.enter('Year *', '2005');
      await app.tap(find.widgetWithText(ElevatedButton, 'Add vessel'));
      expect(find.text('String should have at most 20 characters'), findsOneWidget);
      expect(app.location, '/vessels/new');
    });
  });

  group('products', () {
    testWidgets('list shows fitment badges, sale prices and stock from cents', (tester) async {
      final app = await signedInApp(tester, size: const Size(1280, 1600));
      app.go('/products');
      await app.settle();

      final request = app.backend.calls('GET /products/').last;
      expect(request.query['vessel_id'], fixtureMap('vessel_create')['id'],
          reason: 'fitment is evaluated for the primary vessel');
      expect(find.text('Fits Sea Biscuit'), findsNWidgets(2)); // verified fit + universal
      expect(find.text('Does not fit'), findsOneWidget);
      expect(find.text('Fit unknown — not verified'), findsOneWidget);
      expect(find.text(r'$74.90'), findsOneWidget);
      expect(find.text(r'$89.90'), findsOneWidget); // struck-through regular price
      expect(find.text('Out of stock'), findsOneWidget);
      expect(find.text('1–4 of 4'), findsOneWidget);
    });

    testWidgets('detail shows fitment reasons and adds to cart with server pricing', (tester) async {
      final backend = fixtureBackend();
      final product = fixtureMap('product_detail_fit');
      backend.json('GET /products/${product['id']}', 200, product);
      backend.json('POST /cart/items', 201, fixture('cart_with_item'));
      final app = await signedInApp(tester, backend: backend, size: const Size(1280, 1400));
      app.go('/products/${product['id']}');
      await app.settle();

      expect(find.text('Fits Sea Biscuit'), findsOneWidget);
      expect(find.text('Fits Sea Biscuit (2018 Haines Hunter SF600)'), findsOneWidget);
      expect(find.text('• engine matches verified fitment'), findsOneWidget);
      expect(find.text('47-43026Q06'), findsOneWidget);

      await app.tap(find.byTooltip('Increase quantity'));
      await app.tap(find.text('Add to cart'));
      expect(backend.calls('POST /cart/items').single.body, {'product_id': product['id'], 'quantity': 2});
      expect(find.text('Added 2 × Water Pump Impeller Kit to your cart'), findsOneWidget);
      // Cart badge reflects the server's item count.
      expect(find.text('2'), findsWidgets);
    });

    testWidgets('add-to-cart failures show the server detail', (tester) async {
      final backend = fixtureBackend();
      final product = fixtureMap('product_detail_fit');
      backend.json('GET /products/${product['id']}', 200, product);
      backend.json('POST /cart/items', 409, fixture('error_insufficient_stock'));
      final app = await signedInApp(tester, backend: backend, size: const Size(1280, 1400));
      app.go('/products/${product['id']}');
      await app.settle();
      await app.tap(find.text('Add to cart'));
      expect(find.text('Could not add to cart: Only 12 available'), findsOneWidget);
    });

    testWidgets('the not-yet-public catalogue endpoint fails visibly, not silently', (tester) async {
      final backend = fixtureBackend()..routes.remove('GET /products/');
      final app = await signedInApp(tester, backend: backend);
      app.go('/products');
      await app.settle();
      expect(find.text('Could not load products'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });
  });

  group('cart', () {
    testWidgets('shows lines, issues and the server subtotal; blocks checkout on issues',
        (tester) async {
      final backend = fixtureBackend();
      backend.json('GET /cart/', 200, fixture('cart_with_issues'));
      final app = await signedInApp(tester, backend: backend);
      app.go('/cart');
      await app.settle();

      expect(find.text('Water Pump Impeller Kit'), findsOneWidget);
      expect(find.text('Only 1 in stock — reduce the quantity'), findsOneWidget);
      expect(find.text(r'$149.80'), findsNWidgets(2)); // line total + subtotal
      expect(find.text('Subtotal (2 items)'), findsOneWidget);
      final checkout = tester.widget<ButtonStyleButton>(
          find.ancestor(of: find.text('Proceed to checkout'), matching: find.bySubtype<ButtonStyleButton>()));
      expect(checkout.onPressed, isNull);
    });

    testWidgets('edit quantity, remove, and proceed to checkout', (tester) async {
      final backend = fixtureBackend();
      final withItem = fixtureMap('cart_with_item');
      final line = (withItem['items'] as List).first as Map;
      backend.json('GET /cart/', 200, withItem);
      backend.on('PATCH /cart/items/${line['id']}', (r) {
        final q = (r.body as Map)['quantity'] as int;
        final unit = line['unit_price_cents'] as int;
        return FakeResponse(200, {
          ...withItem,
          'items': [
            {...line, 'quantity': q, 'line_total_cents': unit * q},
          ],
          'subtotal_cents': unit * q,
          'item_count': q,
        });
      });
      backend.json('DELETE /cart/items/${line['id']}', 200, fixture('cart_empty'));
      final app = await signedInApp(tester, backend: backend);
      app.go('/cart');
      await app.settle();

      await app.tap(find.byTooltip('Increase quantity of Water Pump Impeller Kit'));
      expect(backend.calls('PATCH /cart/items/${line['id']}').single.body, {'quantity': 3});
      expect(find.text('Subtotal (3 items)'), findsOneWidget);
      expect(find.text(r'$224.70'), findsNWidgets(2));

      await app.tap(find.text('Proceed to checkout'));
      expect(app.location, '/checkout');

      app.go('/cart');
      await app.settle();
      await app.tap(find.byTooltip('Remove Water Pump Impeller Kit from cart'));
      expect(backend.calls('DELETE /cart/items/${line['id']}'), hasLength(1));
      expect(find.text('Your cart is empty'), findsOneWidget);
    });
  });

  group('profile', () {
    testWidgets('shows the profile and saves name/phone only via PATCH /users/me', (tester) async {
      final backend = fixtureBackend();
      backend.json('GET /orders/', 200, []);
      backend.on('PATCH /users/me', (r) => FakeResponse(200, {
            ...fixtureMap('auth_me'),
            ...(r.body as Map).cast<String, dynamic>(),
          }));
      final app = await signedInApp(tester, backend: backend, size: const Size(600, 1400));
      app.go('/profile');
      await app.settle();
      expect(find.text('Fixture Skipper'), findsOneWidget);

      app.go('/profile/edit');
      await app.settle();
      await tester.enterText(find.byType(TextFormField).first, 'Skipper Two');
      await app.tap(find.widgetWithText(ElevatedButton, 'Save Changes'));
      final body = backend.calls('PATCH /users/me').single.body as Map;
      expect(body.keys, unorderedEquals(['full_name', 'phone']));
      expect(body['full_name'], 'Skipper Two');
      expect(app.location, '/profile');
      expect(find.text('Skipper Two'), findsOneWidget);
    });
  });

  group('accessibility and layout', () {
    testWidgets('large text does not overflow the shop or cart', (tester) async {
      final backend = fixtureBackend();
      backend.json('GET /cart/', 200, fixture('cart_with_item'));
      final app = await signedInApp(tester, backend: backend, textScale: 2.0);
      app.go('/products');
      await app.settle();
      expect(tester.takeException(), isNull);
      app.go('/cart');
      await app.settle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('wide layouts use a navigation rail; phones a bottom bar', (tester) async {
      var app = await signedInApp(tester, size: const Size(1280, 900));
      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      await tester.pumpWidget(const SizedBox());
      app = await signedInApp(tester);
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(app.location, '/');
    });

    testWidgets('tap targets and labels meet guidelines on sign-in and cart', (tester) async {
      final handle = tester.ensureSemantics();
      final app = AppHarness(tester, gateway: FakeAuthGateway(), backend: fixtureBackend());
      await app.start();
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      handle.dispose();
    });

    testWidgets('cart controls are labelled and large enough', (tester) async {
      final handle = tester.ensureSemantics();
      final backend = fixtureBackend();
      backend.json('GET /cart/', 200, fixture('cart_with_item'));
      final app = await signedInApp(tester, backend: backend);
      app.go('/cart');
      await app.settle();
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      handle.dispose();
    });
  });
}
