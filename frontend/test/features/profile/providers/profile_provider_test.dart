import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';

void main() {
  group('CheckoutState - setError', () {
    test('setError is handled via copyWith', () {
      const state = CheckoutState(isProcessing: true);
      final withError = state.copyWith(
        isProcessing: false,
        error: 'Payment declined',
      );

      expect(withError.isProcessing, false);
      expect(withError.error, 'Payment declined');
    });

    test('error can be cleared', () {
      const state = CheckoutState(error: 'Previous error');
      final cleared = state.copyWith(error: null);

      expect(cleared.error, isNull);
    });
  });

  group('CheckoutState - clientSecret', () {
    test('stores client secret from payment intent', () {
      const state = CheckoutState();
      final withSecret = state.copyWith(
        clientSecret: 'pi_secret_test',
        orderId: 'order-123',
      );

      expect(withSecret.clientSecret, 'pi_secret_test');
      expect(withSecret.orderId, 'order-123');
    });
  });
}
