import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge_stub.dart'
    if (dart.library.js_interop) 'package:helm_marine/features/checkout/payment/stripe_web_bridge_web.dart' as impl;

/// Stripe.js could not be loaded, or the Payment Element could not be shown.
/// Never a payment result: the card form is simply unavailable.
class StripeWebFailure implements Exception {
  const StripeWebFailure(this.message);

  final String message;

  @override
  String toString() => message;
}

/// What `stripe.confirmPayment(...)` reported. It is never a payment result:
/// the order is paid only when the server says so (verified webhook).
sealed class StripeWebConfirmResult {
  const StripeWebConfirmResult();
}

/// Stripe returned an error (decline, validation, authentication failure…).
/// The same PaymentIntent can be confirmed again.
class StripeWebConfirmError extends StripeWebConfirmResult {
  const StripeWebConfirmError({required this.message, this.type, this.code, this.declineCode});

  /// Stripe's customer-facing message (safe to show).
  final String message;
  final String? type;
  final String? code;
  final String? declineCode;
}

/// No error: the confirmation was submitted. [status] is what Stripe.js saw
/// (`succeeded`, `processing`, …) and is informational only.
class StripeWebConfirmSubmitted extends StripeWebConfirmResult {
  const StripeWebConfirmSubmitted({this.status});

  final String? status;
}

/// Query parameters Stripe appends when it returns the browser to
/// `return_url` after a full-page redirect (e.g. some 3-D Secure flows).
class StripeRedirectReturn {
  const StripeRedirectReturn({required this.paymentIntentId, this.redirectStatus});

  final String paymentIntentId;
  final String? redirectStatus;
}

/// The browser side of Stripe card payments on web: Stripe.js loading, the
/// Payment Element in a platform view, and `confirmPayment`. One bridge
/// serves one mounted Payment Element.
abstract interface class StripeWebBridge {
  /// Injects `https://js.stripe.com/v3/` (once per page) and waits for it.
  /// Throws [StripeWebFailure] when it cannot be loaded (offline, CSP, blocked).
  Future<void> loadStripeJs();

  /// The host widget the Payment Element is mounted into. [onCreated] is called
  /// with the platform view id once the host element exists.
  Widget buildHost({required ValueChanged<int> onCreated});

  /// Mounts the Payment Element for [clientSecret] into the host [viewId] and
  /// waits until it is ready. [onResize] reports the element's content height.
  /// Throws [StripeWebFailure] when the element cannot be shown.
  Future<void> mount({
    required int viewId,
    required String publishableKey,
    required String clientSecret,
    ValueChanged<double>? onResize,
  });

  /// `stripe.confirmPayment({elements, redirect: 'if_required', confirmParams: {return_url}})`.
  Future<StripeWebConfirmResult> confirm({required String returnUrl});

  /// Where Stripe returns the browser after a redirect: the order's page.
  String returnUrlFor(String orderId);

  /// Destroys the Payment Element (the loaded Stripe.js stays cached).
  void dispose();
}

/// Creates a [StripeWebBridge] per Payment Element, or null when this build
/// pays with the native PaymentSheet instead (Android / iOS).
typedef StripeWebBridgeFactory = StripeWebBridge Function();

final stripeWebBridgeFactoryProvider = Provider<StripeWebBridgeFactory?>((ref) => impl.stripeWebBridgeFactory);

/// Reads (once) and clears Stripe's redirect-return query parameters.
final stripeRedirectReturnReaderProvider =
    Provider<StripeRedirectReturn? Function()>((ref) => impl.takeStripeRedirectReturn);
