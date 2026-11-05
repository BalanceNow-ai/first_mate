import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';

/// Where the web card form is. There is deliberately no "paid" phase: after a
/// confirmation the payment panel re-reads the order, and only the server's
/// verified webhook marks it paid.
enum WebCardPhase {
  /// Loading Stripe.js.
  loadingScript,

  /// Stripe.js is loaded; waiting for the platform view host to exist.
  awaitingHost,

  /// Mounting the Payment Element.
  mounting,

  /// The card form is shown and can be confirmed.
  ready,

  /// `stripe.confirmPayment` is in flight (3-D Secure runs inside it).
  confirming,

  /// Stripe accepted the confirmation; the server's result is being polled.
  submitted,

  /// Stripe.js or the Payment Element is unavailable. Never a payment result.
  unavailable,
}

/// The state machine behind the web card form (Stripe Payment Element). It
/// keeps the same PaymentIntent (client secret) for every attempt: a decline
/// leaves the form mounted so the customer can retry with the same intent.
class WebCardPaymentController extends ChangeNotifier {
  WebCardPaymentController({
    required this.bridge,
    required this.orderId,
    required this.clientSecret,
    required this.publishableKey,
    required this.onSubmitted,
  });

  final StripeWebBridge bridge;
  final String orderId;
  final String clientSecret;
  final String? publishableKey;

  /// Called after Stripe accepted a confirmation: poll the server's order.
  final Future<void> Function() onSubmitted;

  static const double defaultHeight = 300;
  static const double minHeight = 160;
  static const double maxHeight = 720;

  WebCardPhase _phase = WebCardPhase.loadingScript;
  String? _unavailableReason;
  String? _cardError;
  int? _viewId;
  double _height = defaultHeight;
  int _confirmAttempts = 0;
  bool _disposed = false;

  WebCardPhase get phase => _phase;

  /// Why the card form is unavailable (only in [WebCardPhase.unavailable]).
  String? get unavailableReason => _unavailableReason;

  /// Stripe's message for the last failed confirmation (decline, validation…).
  String? get cardError => _cardError;

  /// Height for the Payment Element host, from the element's own size.
  double get height => _height;

  int get confirmAttempts => _confirmAttempts;

  /// Whether the host view (and so the Payment Element) should be on screen.
  bool get showsHost => switch (_phase) {
        WebCardPhase.awaitingHost ||
        WebCardPhase.mounting ||
        WebCardPhase.ready ||
        WebCardPhase.confirming ||
        WebCardPhase.submitted =>
          true,
        WebCardPhase.loadingScript || WebCardPhase.unavailable => false,
      };

  bool get canPay => _phase == WebCardPhase.ready;

  void _set(WebCardPhase phase, {String? unavailableReason, String? Function()? cardError}) {
    if (_disposed) return;
    _phase = phase;
    _unavailableReason = phase == WebCardPhase.unavailable ? unavailableReason : null;
    if (cardError != null) _cardError = cardError();
    notifyListeners();
  }

  /// Loads Stripe.js; the host view is then shown and [attachHost] mounts it.
  Future<void> start() async {
    final key = publishableKey;
    if (key == null || key.isEmpty) {
      _set(WebCardPhase.unavailable,
          unavailableReason: 'Card payments are not configured on this server (no Stripe publishable key).');
      return;
    }
    _viewId = null;
    _set(WebCardPhase.loadingScript, cardError: () => null);
    try {
      await bridge.loadStripeJs();
    } catch (e) {
      _set(WebCardPhase.unavailable, unavailableReason: _reason(e));
      return;
    }
    _set(WebCardPhase.awaitingHost);
  }

  /// Called by the host view once its element exists.
  Future<void> attachHost(int viewId) async {
    if (_disposed || _viewId == viewId) return;
    if (_phase != WebCardPhase.awaitingHost) return;
    _viewId = viewId;
    _set(WebCardPhase.mounting);
    try {
      await bridge.mount(
        viewId: viewId,
        publishableKey: publishableKey!,
        clientSecret: clientSecret,
        onResize: _onResize,
      );
    } catch (e) {
      _set(WebCardPhase.unavailable, unavailableReason: _reason(e));
      return;
    }
    if (_phase == WebCardPhase.mounting) _set(WebCardPhase.ready);
  }

  void _onResize(double contentHeight) {
    if (_disposed) return;
    final h = (contentHeight + 12).clamp(minHeight, maxHeight).toDouble();
    if ((h - _height).abs() < 1) return;
    _height = h;
    notifyListeners();
  }

  /// "Try again" from [WebCardPhase.unavailable]: reload and remount.
  Future<void> retry() async {
    if (_phase != WebCardPhase.unavailable) return;
    await start();
  }

  /// Confirms the same PaymentIntent with the card in the Payment Element.
  /// A Stripe error is shown and the form stays ready for another attempt;
  /// no error means "submitted" and the server's order is polled.
  Future<void> pay() async {
    if (_phase != WebCardPhase.ready) return;
    _confirmAttempts++;
    _set(WebCardPhase.confirming, cardError: () => null);
    StripeWebConfirmResult result;
    try {
      result = await bridge.confirm(returnUrl: bridge.returnUrlFor(orderId));
    } catch (_) {
      result = const StripeWebConfirmError(message: 'The card payment could not be completed. Try again.');
    }
    if (_disposed) return;
    switch (result) {
      case StripeWebConfirmError(:final message):
        _set(WebCardPhase.ready, cardError: () => message);
      case StripeWebConfirmSubmitted():
        _set(WebCardPhase.submitted);
        try {
          await onSubmitted();
        } finally {
          // The panel now shows what the server reported. If the order is
          // still awaiting payment (e.g. the bank wants authentication again,
          // or no confirmation arrived yet) the same intent can be confirmed
          // again; Stripe never charges one PaymentIntent twice.
          if (_phase == WebCardPhase.submitted) _set(WebCardPhase.ready);
        }
    }
  }

  static String _reason(Object error) =>
      error is StripeWebFailure ? error.message : 'The secure card form could not be loaded.';

  @override
  void dispose() {
    _disposed = true;
    bridge.dispose();
    super.dispose();
  }
}
