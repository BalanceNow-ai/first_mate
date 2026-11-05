// Checkout is rebuilt in client pass 2; these tests cover what pass 1 keeps:
// the screen compiles against the typed cart and shows server-computed cents.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/checkout/screens/checkout_screen.dart';

import '../../../helpers/fakes.dart';

class _FixedCart extends CartNotifier {
  _FixedCart(this.cart);

  final Cart cart;

  @override
  Future<Cart> build() async => cart;
}

void main() {
  Widget build(Cart cart) {
    return ProviderScope(
      overrides: [
        ...baseTestOverrides(),
        cartProvider.overrideWith(() => _FixedCart(cart)),
      ],
      child: const MaterialApp(home: CheckoutScreen()),
    );
  }

  void tall(WidgetTester tester) {
    tester.view.physicalSize = const Size(1080, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
  }

  final cartWithItem = Cart.fromJson(fixtureMap('cart_with_item'));

  testWidgets('shows title, steps and delivery options', (tester) async {
    tall(tester);
    await tester.pumpWidget(build(cartWithItem));
    await tester.pumpAndSettle();

    expect(find.text('Checkout'), findsOneWidget);
    expect(find.text('Payment'), findsOneWidget);
    expect(find.text('Confirm'), findsOneWidget);
    expect(find.text('Delivery Method'), findsOneWidget);
    expect(find.text('Standard Shipping'), findsOneWidget);
    expect(find.text('Click & Collect'), findsOneWidget);
    expect(find.text('Continue to Payment'), findsOneWidget);
    expect(find.byType(PageView), findsOneWidget);
  });

  testWidgets('order summary shows the server subtotal from cents', (tester) async {
    tall(tester);
    await tester.pumpWidget(build(cartWithItem));
    await tester.pumpAndSettle();

    expect(find.text('Order Summary'), findsOneWidget);
    expect(find.text('2 items'), findsOneWidget);
    expect(find.text(r'$149.80'), findsOneWidget);
    // Shipping is never computed on the client.
    expect(find.text('Quoted at payment'), findsOneWidget);
    expect(find.text('FREE'), findsNothing);
  });
}
