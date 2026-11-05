import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';

import '../../helpers/fakes.dart';
import '../orders/commerce_harness.dart';

final quoteTime = DateTime.parse(fixtureMap('quote_courier')['created_at'] as String).add(const Duration(minutes: 1));

CommerceHarness harness(WidgetTester tester, FakeBackend backend) => CommerceHarness(
      tester,
      backend: backend,
      overrides: [
        checkoutClockProvider.overrideWithValue(() => quoteTime),
        paymentPollIntervalProvider.overrideWithValue(Duration.zero),
        paymentPollAttemptsProvider.overrideWithValue(2),
      ],
    );

FakeBackend checkoutBackend({String options = 'shipping_options'}) {
  final b = fixtureBackend();
  b.json('GET /config/public', 200, fixture('config_public_helm_dash'));
  b.json('GET /cart/', 200, fixture('cart_with_item'));
  b.json('GET /shipping/options', 200, fixture(options));
  b.json('GET /loyalty/entitlements', 200, fixture('loyalty_entitlements_issued'));
  return b;
}

void main() {
  testWidgets('dangerous goods: courier and Helm Dash are shown disabled with the server reason', (tester) async {
    final app = harness(tester, checkoutBackend(options: 'shipping_options_dangerous_goods'));
    await app.start();
    app.go('/checkout');
    await app.pump();

    expect(find.textContaining('Dangerous goods in your cart'), findsOneWidget);
    expect(find.textContaining('Unavailable — Coastal distress flare kit (synthetic) cannot be sent by courier'),
        findsOneWidget);
    expect(find.textContaining('Unavailable — Coastal distress flare kit (synthetic) cannot be sent by Helm Dash'),
        findsOneWidget);
    await app.tap(find.text('Helm Dash — delivered to your vessel'));
    expect(find.text('Where should we deliver?'), findsNothing, reason: 'a disabled option cannot be chosen');
    expect(find.text('Free · collect from Helm Marine, Westhaven Marina, Auckland'), findsOneWidget);
    await app.stop();
  });

  testWidgets('click & collect → review (server preview, discount) → idempotent order → TEST MODE payment',
      (tester) async {
    final backend = checkoutBackend();
    final order = fixtureMap('order_click_and_collect_created');
    final orderId = order['id'] as String;
    var current = order;
    backend.json('POST /orders/checkout/preview', 200, fixture('checkout_preview_click_and_collect'));
    backend.on('POST /orders/checkout', (_) => FakeResponse(201, order));
    backend.on('GET /orders/$orderId', (_) => FakeResponse(200, current));
    backend.json('POST /payments/orders/$orderId/intent', 200, fixture('payment_intent_local'));
    final pi = fixtureMap('payment_intent_local')['payment_intent_id'];
    backend.on('POST /payments/local/$pi/confirm', (r) {
      current = {...fixtureMap('order_payment_failed'), 'id': orderId};
      return FakeResponse(200, fixture('payment_local_decline'));
    });
    final app = harness(tester, backend);
    await app.start();
    app.go('/checkout');
    await app.pump();

    expect(find.text('Continue to review'), findsOneWidget);
    await app.tap(find.text('Click & collect'));
    expect(find.text('Pickup location'), findsOneWidget);
    expect(find.text(r'Shipping $0.00'), findsOneWidget);
    await app.tap(find.text('Continue to review'));

    expect(backend.calls('POST /orders/checkout/preview').single.body, {
      'delivery_type': 'click_and_collect',
      'payment_method': 'card',
    });
    expect(find.text('Shipping (click & collect)'), findsOneWidget);
    expect(find.textContaining('Code CREW-'), findsOneWidget);
    expect(find.textContaining('Place order'), findsOneWidget);

    await app.tap(find.textContaining('Place order'));
    final placed = backend.calls('POST /orders/checkout').single;
    expect(placed.headers['Idempotency-Key'], matches(RegExp(r'^[A-Za-z0-9_\-:.]{8,100}$')));
    expect(app.container.read(checkoutProvider).orderId, orderId);

    // Payment step: methods from config, test-mode panel.
    expect(find.text('TEST MODE — no real charge'), findsOneWidget);
    expect(find.textContaining('Not available — Afterpay is not offered'), findsOneWidget);
    expect(find.textContaining('Not available — Laybuy is not offered'), findsOneWidget);

    await app.tap(find.text('Simulate decline'));
    expect(find.text('Payment declined'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(find.text('Cancel order'), findsOneWidget);
    await app.stop();
  });

  testWidgets('courier: postcode validation, server quote, quote_cart_changed asks for a new quote', (tester) async {
    final backend = checkoutBackend();
    backend.json('POST /shipping/quotes', 201, fixture('quote_courier'));
    backend.json('POST /orders/checkout/preview', 409, fixture('error_quote_cart_changed'));
    final app = harness(tester, backend);
    await app.start();
    app.go('/checkout');
    await app.pump();

    await app.tap(find.text('Standard courier'));
    await app.enter('Postcode *', '10');
    await app.tap(find.text('Get courier quote'));
    expect(find.text('Enter a 4-digit NZ postcode'), findsOneWidget);
    expect(backend.calls('POST /shipping/quotes'), isEmpty);

    await app.enter('Full name *', 'Fixture Shopper');
    await app.enter('Street address *', '1 Quay Street');
    await app.enter('Town or city *', 'Auckland');
    await app.enter('Postcode *', '1010');
    await app.enter('Phone *', '021 555 0101');
    await app.tap(find.text('Get courier quote'));
    expect(find.text('Courier quote'), findsOneWidget);
    expect(find.text(r'$12.90'), findsOneWidget);
    expect(find.text('Development rate card — local test pricing'), findsOneWidget);

    await app.tap(find.text('Continue to review'));
    expect(find.text('Your cart changed'), findsOneWidget);
    expect(find.text('Get a new quote'), findsOneWidget);
    await app.stop();
  });

  testWidgets('phone width with 2x text: delivery step renders without overflow', (tester) async {
    final app = harness(tester, checkoutBackend(options: 'shipping_options_dangerous_goods'));
    await app.start(size: const Size(380, 2400), textScale: 2.0);
    app.go('/checkout');
    await app.pump();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(find.text('Continue to review'), 400, scrollable: find.byType(Scrollable).last);
    expect(tester.takeException(), isNull);
    await app.stop();
  });
}
