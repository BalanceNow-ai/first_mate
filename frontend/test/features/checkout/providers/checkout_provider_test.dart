import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';

void main() {
  group('CheckoutState', () {
    test('default state has correct initial values', () {
      const state = CheckoutState();

      expect(state.currentStep, 0);
      expect(state.deliveryType, 'courier');
      expect(state.shippingAddress, isEmpty);
      expect(state.helmDashCoordinates, isNull);
      expect(state.paymentMethod, 'card');
      expect(state.orderId, isNull);
      expect(state.clientSecret, isNull);
      expect(state.isProcessing, false);
      expect(state.error, isNull);
    });

    test('copyWith creates modified state', () {
      const state = CheckoutState();
      final modified = state.copyWith(
        deliveryType: 'helm_dash',
        currentStep: 1,
      );

      expect(modified.deliveryType, 'helm_dash');
      expect(modified.currentStep, 1);
      expect(modified.paymentMethod, 'card'); // unchanged
      expect(modified.shippingAddress, isEmpty); // unchanged
    });

    test('copyWith preserves all fields', () {
      final state = const CheckoutState(
        currentStep: 1,
        deliveryType: 'helm_dash',
        shippingAddress: {'city': 'Auckland'},
        paymentMethod: 'afterpay',
        orderId: 'order-123',
        clientSecret: 'secret-456',
        isProcessing: true,
        error: 'some error',
      );

      final modified = state.copyWith(currentStep: 2);

      expect(modified.currentStep, 2); // changed
      expect(modified.deliveryType, 'helm_dash'); // preserved
      expect(modified.shippingAddress, {'city': 'Auckland'}); // preserved
      expect(modified.paymentMethod, 'afterpay'); // preserved
      expect(modified.orderId, 'order-123'); // preserved
      expect(modified.clientSecret, 'secret-456'); // preserved
      expect(modified.isProcessing, true); // preserved
    });

    test('copyWith clears error when null is passed', () {
      const state = CheckoutState(error: 'old error');
      final modified = state.copyWith(error: null);

      // error field always takes the passed value (including null)
      expect(modified.error, isNull);
    });

    test('copyWith sets helm dash coordinates', () {
      const state = CheckoutState();
      final modified = state.copyWith(
        helmDashCoordinates: {'lat': -36.84, 'lng': 174.75},
      );

      expect(modified.helmDashCoordinates, isNotNull);
      expect(modified.helmDashCoordinates!['lat'], -36.84);
      expect(modified.helmDashCoordinates!['lng'], 174.75);
    });

    test('delivery type options are strings', () {
      const courier = CheckoutState(deliveryType: 'courier');
      const helmDash = CheckoutState(deliveryType: 'helm_dash');
      const clickCollect = CheckoutState(deliveryType: 'click_and_collect');

      expect(courier.deliveryType, 'courier');
      expect(helmDash.deliveryType, 'helm_dash');
      expect(clickCollect.deliveryType, 'click_and_collect');
    });

    test('payment method options are strings', () {
      const card = CheckoutState(paymentMethod: 'card');
      const afterpay = CheckoutState(paymentMethod: 'afterpay');
      const laybuy = CheckoutState(paymentMethod: 'laybuy');

      expect(card.paymentMethod, 'card');
      expect(afterpay.paymentMethod, 'afterpay');
      expect(laybuy.paymentMethod, 'laybuy');
    });
  });
}
