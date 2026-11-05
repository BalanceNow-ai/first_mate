import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:helm_marine/features/checkout/payment/stripe_payment.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';

/// Whether flutter_stripe's native PaymentSheet works here (false on web).
final stripeNativeSheetSupportedProvider = Provider<bool>((ref) => stripeSupportedHere);

/// Whether this device can pay with the server's configured provider. Checked
/// at the review step so "Place order" never reserves stock (creates an order)
/// that this platform cannot charge.
class PaymentReadiness {
  const PaymentReadiness.ready()
      : ready = true,
        reason = null,
        retryable = false;

  const PaymentReadiness.blocked(String this.reason, {this.retryable = false}) : ready = false;

  final bool ready;
  final String? reason;

  /// The problem may be transient (e.g. Stripe.js failed to load).
  final bool retryable;
}

final paymentReadinessProvider = FutureProvider.autoDispose<PaymentReadiness>((ref) async {
  final config = await ref.watch(publicConfigProvider.future);
  final payments = config.payments;
  final card = payments.method('card');
  if (!payments.enabled || card == null || !card.enabled) {
    return PaymentReadiness.blocked(card?.reason ?? 'Card payments are not available on this server right now.');
  }
  switch (payments.provider) {
    case 'local':
      return const PaymentReadiness.ready();
    case 'stripe':
      final key = payments.stripePublishableKey;
      if (key == null || key.isEmpty) {
        return const PaymentReadiness.blocked('Card payments are not configured on this server (no Stripe key).');
      }
      final webBridge = ref.watch(stripeWebBridgeFactoryProvider);
      if (webBridge != null) {
        // Web: Stripe.js must load here before any order exists.
        final bridge = webBridge();
        try {
          await bridge.loadStripeJs();
          return const PaymentReadiness.ready();
        } on StripeWebFailure catch (e) {
          return PaymentReadiness.blocked('Card payments are unavailable right now: ${e.message}', retryable: true);
        } catch (_) {
          return const PaymentReadiness.blocked('Card payments are unavailable right now.', retryable: true);
        } finally {
          bridge.dispose();
        }
      }
      if (ref.watch(stripeNativeSheetSupportedProvider)) return const PaymentReadiness.ready();
      return const PaymentReadiness.blocked('Card payments are not available in this version of the app.');
    default:
      return PaymentReadiness.blocked('Unknown payment provider "${payments.provider}".');
  }
});
