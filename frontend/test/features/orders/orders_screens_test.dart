import 'package:flutter_test/flutter_test.dart';

import '../../helpers/fakes.dart';
import 'commerce_harness.dart';

void main() {
  testWidgets('order history lists server orders; detail shows amounts, tracking label and Helm Dash link',
      (tester) async {
    final backend = fixtureBackend();
    final list = fixtureMap('orders_list');
    final courier = fixtureMap('order_with_test_tracking');
    final hd = fixtureMap('order_helm_dash_paid');
    backend.json('GET /orders/', 200, list);
    backend.json('GET /orders/${courier['id']}', 200, courier);
    backend.json('GET /orders/${hd['id']}', 200, hd);
    backend.json('GET /helm-dash/deliveries', 200, fixture('helm_dash_deliveries'));
    final app = CommerceHarness(tester, backend: backend);
    await app.start();
    app.go('/orders');
    await app.pump();
    expect(backend.calls('GET /orders/').single.query, {'page': '1', 'page_size': '20'});
    for (final o in list['items'] as List) {
      expect(find.text('Order ${(o as Map)['order_number']}'), findsOneWidget);
    }
    expect(find.text('Cancelled'), findsOneWidget);

    app.go('/orders/${courier['id']}');
    await app.pump();
    expect(find.text('TEST LABEL — not a real courier booking'), findsOneWidget);
    expect(find.textContaining('Tracking number: TEST-'), findsOneWidget);
    expect(find.text(r'$123.80'), findsOneWidget, reason: 'total from total_cents');

    app.go('/orders/${hd['id']}');
    await app.pump();
    expect(find.text('Track delivery'), findsOneWidget);
    await app.tap(find.text('Track delivery'));
    expect(app.location, startsWith('/dash/'));
    await app.stop();
  });

  testWidgets('pending order offers pay / cancel; cancel explains items return to the cart', (tester) async {
    final backend = fixtureBackend();
    final pending = fixtureMap('order_payment_failed');
    backend.json('GET /orders/${pending['id']}', 200, pending);
    backend.json('POST /orders/${pending['id']}/cancel', 200, {...fixtureMap('order_cancelled'), 'id': pending['id']});
    final app = CommerceHarness(tester, backend: backend);
    await app.start();
    app.go('/orders/${pending['id']}');
    await app.pump();
    expect(find.text('Retry payment'), findsOneWidget);
    expect(find.text('Cancelling returns the items to your cart.'), findsOneWidget);
    await app.tap(find.text('Cancel order'));
    expect(find.text('Cancel this order?'), findsOneWidget);
    await app.tap(find.text('Cancel order').last);
    expect(backend.calls('POST /orders/${pending['id']}/cancel'), hasLength(1));
    expect(find.text('Order cancelled — the items are back in your cart.'), findsOneWidget);
    await app.stop();
  });
}
