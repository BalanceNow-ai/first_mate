import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';

import '../../helpers/fakes.dart';

const _address = ShippingAddress(
  name: 'Fixture Shopper',
  line1: '1 Quay Street',
  city: 'Auckland',
  postcode: '1010',
  phone: '021 555 0101',
);

/// Quote fixtures are real captures; pin the clock to just after they were issued.
final quoteTime = DateTime.parse(fixtureMap('quote_courier')['created_at'] as String).add(const Duration(minutes: 1));

Future<ProviderContainer> signedIn(FakeBackend backend) async {
  final container = ProviderContainer(
    overrides: [
      ...testOverrides(gateway: fixtureGateway(), backend: backend),
      checkoutClockProvider.overrideWithValue(() => quoteTime),
    ],
    retry: (_, _) => null,
  );
  addTearDown(container.dispose);
  container.read(authControllerProvider);
  await until(() => container.read(authControllerProvider).isSignedIn);
  return container;
}

void main() {
  test('idempotency keys match the server pattern and are unique', () {
    final pattern = RegExp(r'^[A-Za-z0-9_\-:.]{8,100}$');
    final keys = {for (var i = 0; i < 50; i++) newIdempotencyKey()};
    expect(keys, hasLength(50));
    expect(keys.every(pattern.hasMatch), isTrue);
  });

  test('courier quote then preview send the server contract', () async {
    final backend = fixtureBackend();
    backend.json('POST /shipping/quotes', 201, fixture('quote_courier'));
    backend.json('POST /orders/checkout/preview', 200, fixture('checkout_preview_courier'));
    final c = await signedIn(backend);
    final ctl = c.read(checkoutProvider.notifier);

    ctl.selectDelivery(DeliveryType.courier);
    final quote = await ctl.quoteCourier(postcode: '1010', city: 'Auckland');
    expect(quote!.postcode, '1010');
    expect(backend.calls('POST /shipping/quotes').single.body, {
      'delivery_type': 'courier',
      'destination': {'postcode': '1010', 'city': 'Auckland'},
    });

    final preview = await ctl.preview(CheckoutRequest(
      deliveryType: DeliveryType.courier,
      quoteId: quote.id,
      shippingAddress: _address,
    ));
    expect(preview!.totalCents, 12380);
    final body = backend.calls('POST /orders/checkout/preview').single.body as Map;
    expect(body['quote_id'], quote.id);
    expect(body['payment_method'], 'card');
    expect((body['shipping_address'] as Map)['postcode'], '1010');
  });

  test('a lost response is retried with the SAME Idempotency-Key; double taps send once', () async {
    final backend = fixtureBackend();
    var calls = 0;
    backend.on('POST /orders/checkout', (r) async {
      calls++;
      if (calls == 1) throw Exception('connection reset');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      return FakeResponse(calls == 2 ? 201 : 200, fixture('order_checkout_created'));
    });
    final c = await signedIn(backend);
    final ctl = c.read(checkoutProvider.notifier);
    ctl.selectDelivery(DeliveryType.clickAndCollect);
    const req = CheckoutRequest(deliveryType: DeliveryType.clickAndCollect);

    expect(await ctl.placeOrder(req), isNull);
    final err = ApiError.from(c.read(checkoutProvider).placeError!)!;
    expect(err.isNetwork, isTrue);
    final key = c.read(checkoutProvider).attemptKey;
    expect(key, isNotNull);

    // Double tap: the second call is ignored while the first is in flight.
    final first = ctl.placeOrder(req);
    final second = ctl.placeOrder(req);
    expect(c.read(checkoutProvider).placing, isTrue);
    expect(await second, isNull);
    final order = await first;
    expect(order!.id, fixtureMap('order_checkout_created')['id']);
    expect(c.read(checkoutProvider).orderId, order.id);

    final sent = backend.calls('POST /orders/checkout');
    expect(sent, hasLength(2));
    expect(sent.map((r) => r.headers['Idempotency-Key']).toSet(), {key});

    ctl.reset();
    expect(c.read(checkoutProvider).attemptKey, isNull, reason: 'a new attempt gets a new key');
  });

  test('quote_cart_changed drops the quote so the user re-quotes', () async {
    final backend = fixtureBackend();
    backend.json('POST /shipping/quotes', 201, fixture('quote_courier'));
    backend.json('POST /orders/checkout/preview', 409, fixture('error_quote_cart_changed'));
    final c = await signedIn(backend);
    final ctl = c.read(checkoutProvider.notifier);
    ctl.selectDelivery(DeliveryType.courier);
    final q = await ctl.quoteCourier(postcode: '1010');
    await ctl.preview(CheckoutRequest(deliveryType: DeliveryType.courier, quoteId: q!.id, shippingAddress: _address));
    final s = c.read(checkoutProvider);
    expect(ApiError.from(s.previewError!)!.code, 'quote_cart_changed');
    expect(s.quote, isNull);
  });

  test('quote errors are kept with their server code', () async {
    final backend = fixtureBackend();
    backend.json('POST /shipping/quotes', 422, fixture('error_outside_operating_area'));
    final c = await signedIn(backend);
    final ctl = c.read(checkoutProvider.notifier);
    ctl.selectDelivery(DeliveryType.helmDash);
    expect(await ctl.quoteHelmDash(lat: -41.29, lng: 174.78), isNull);
    expect(ApiError.from(c.read(checkoutProvider).quoteError!)!.code, 'outside_operating_area');
  });
}
