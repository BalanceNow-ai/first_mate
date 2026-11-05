import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/orders/data/commerce_api.dart';
import 'package:helm_marine/features/orders/providers/orders_providers.dart';

/// Delay between order re-reads while waiting for the payment result.
final paymentPollIntervalProvider = Provider<Duration>((ref) => const Duration(seconds: 2));

/// How many re-reads before reporting that confirmation is still pending.
final paymentPollAttemptsProvider = Provider<int>((ref) => 30);

/// What the payment panel should show, derived from the server's order.
enum PaymentPhase {
  loading,
  ready,
  processing,
  requiresAction,
  failed,
  paid,

  /// The provider took a payment the server could not apply to the order
  /// (amount mismatch, or paid after the reservation was released). Not paid:
  /// staff review it and contact or refund the customer.
  underReview,
  cancelled,
  expired,
  closed,
  error,
}

PaymentPhase phaseOf(Order order) {
  if (order.isUnderPaymentReview) return PaymentPhase.underReview;
  if (order.isPaid) return PaymentPhase.paid;
  switch (order.status) {
    case 'cancelled':
      return PaymentPhase.cancelled;
    case 'expired':
      return PaymentPhase.expired;
    case 'pending_payment':
      break;
    default:
      return PaymentPhase.closed;
  }
  return switch (order.paymentStatus) {
    'failed' => PaymentPhase.failed,
    'requires_action' => PaymentPhase.requiresAction,
    'processing' => PaymentPhase.processing,
    _ => PaymentPhase.ready,
  };
}

class PaymentState {
  const PaymentState({
    this.order,
    this.intent,
    this.busy = false,
    this.waiting = false,
    this.waitTimedOut = false,
    this.error,
    this.loadError,
    this.lastTestEvent,
  });

  final Order? order;
  final PaymentIntentInfo? intent;

  /// A confirm / cancel / intent request is in flight.
  final bool busy;

  /// Re-reading the order until the provider's result is applied.
  final bool waiting;
  final bool waitTimedOut;
  final Object? error;
  final Object? loadError;

  /// The last TEST MODE confirmation (for the test panel's log).
  final LocalConfirmResult? lastTestEvent;

  PaymentPhase get phase {
    final o = order;
    if (o == null) return loadError != null ? PaymentPhase.error : PaymentPhase.loading;
    return phaseOf(o);
  }

  PaymentState copyWith({
    Order? order,
    PaymentIntentInfo? Function()? intent,
    bool? busy,
    bool? waiting,
    bool? waitTimedOut,
    Object? Function()? error,
    Object? Function()? loadError,
    LocalConfirmResult? lastTestEvent,
  }) =>
      PaymentState(
        order: order ?? this.order,
        intent: intent == null ? this.intent : intent(),
        busy: busy ?? this.busy,
        waiting: waiting ?? this.waiting,
        waitTimedOut: waitTimedOut ?? this.waitTimedOut,
        error: error == null ? this.error : error(),
        loadError: loadError == null ? this.loadError : loadError(),
        lastTestEvent: lastTestEvent ?? this.lastTestEvent,
      );
}

/// Drives paying for one order. The client never marks an order paid: after
/// any confirmation it re-reads `GET /orders/{id}` until the server reports
/// paid, failed, requires_action or the reservation ends.
final paymentControllerProvider =
    NotifierProvider.autoDispose.family<PaymentController, PaymentState, String>(PaymentController.new);

class PaymentController extends Notifier<PaymentState> {
  PaymentController(this.orderId);

  final String orderId;
  bool _disposed = false;

  CommerceApi get _api => ref.read(commerceApiProvider);

  @override
  PaymentState build() {
    ref.watch(commerceApiProvider);
    _disposed = false;
    ref.onDispose(() => _disposed = true);
    Future.microtask(load);
    return const PaymentState();
  }

  bool get _alive => !_disposed && ref.mounted;

  /// Loads the order and, when it can be paid, creates or recovers its intent.
  Future<void> load() async {
    try {
      final order = await _api.order(orderId);
      if (!_alive) return;
      state = state.copyWith(order: order, loadError: () => null);
      await _ensureIntent(order);
    } catch (e) {
      if (_alive) state = state.copyWith(loadError: () => e);
    }
  }

  Future<void> _ensureIntent(Order order) async {
    if (!order.isPendingPayment || !order.canRetryPayment) return;
    if (state.intent != null) return;
    try {
      final intent = await _api.paymentIntent(orderId);
      if (_alive) state = state.copyWith(intent: () => intent, error: () => null);
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
    }
  }

  /// Re-reads the order (e.g. when the reservation countdown ends).
  Future<void> refresh() async {
    try {
      final order = await _api.order(orderId);
      if (_alive) state = state.copyWith(order: order);
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
    }
  }

  /// TEST MODE: simulate [outcome] with the local provider, then wait for the
  /// server's order status.
  Future<void> confirmLocal(LocalPaymentOutcome outcome) async {
    if (state.busy) return;
    state = state.copyWith(busy: true, error: () => null, waitTimedOut: false);
    try {
      // Recover (reuse) the same intent; also refreshes it after a decline.
      final intent = state.intent ?? await _api.paymentIntent(orderId);
      if (!_alive) return;
      state = state.copyWith(intent: () => intent);
      final result = await _api.confirmLocalPayment(intent.paymentIntentId, outcome);
      if (!_alive) return;
      state = state.copyWith(lastTestEvent: result);
      await awaitServerResult();
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
      await refresh();
    } finally {
      if (_alive) state = state.copyWith(busy: false);
    }
  }

  /// After a card confirmation elsewhere (Stripe PaymentSheet / Payment
  /// Element): poll the order until the provider's signed event is applied.
  Future<void> awaitServerResult() async {
    final attempts = ref.read(paymentPollAttemptsProvider);
    final interval = ref.read(paymentPollIntervalProvider);
    state = state.copyWith(waiting: true, waitTimedOut: false);
    try {
      for (var i = 0; i < attempts; i++) {
        final order = await _api.order(orderId);
        if (!_alive) return;
        state = state.copyWith(order: order);
        final phase = phaseOf(order);
        if (phase != PaymentPhase.ready && phase != PaymentPhase.processing) return;
        if (i + 1 < attempts) await Future<void>.delayed(interval);
        if (!_alive) return;
      }
      state = state.copyWith(waitTimedOut: true);
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
    } finally {
      if (_alive) state = state.copyWith(waiting: false);
    }
  }

  /// "Try again" after a decline: recover the (same) intent and show the
  /// payment options again.
  Future<void> retry() async {
    if (state.busy) return;
    state = state.copyWith(busy: true, error: () => null, waitTimedOut: false);
    try {
      final intent = await _api.paymentIntent(orderId);
      if (!_alive) return;
      state = state.copyWith(intent: () => intent);
      await refresh();
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
      await refresh();
    } finally {
      if (_alive) state = state.copyWith(busy: false);
    }
  }

  /// Cancels the unpaid order; the server releases the stock and puts the
  /// items back in the cart.
  Future<bool> cancel() async {
    if (state.busy) return false;
    state = state.copyWith(busy: true, error: () => null);
    try {
      final order = await _api.cancelOrder(orderId);
      if (!_alive) return true;
      state = state.copyWith(order: order, intent: () => null);
      ref.invalidate(cartProvider);
      ref.invalidate(orderHistoryProvider);
      return true;
    } catch (e) {
      if (_alive) state = state.copyWith(error: () => e);
      await refresh();
      return false;
    } finally {
      if (_alive) state = state.copyWith(busy: false);
    }
  }

  /// Records a client-side failure (e.g. the Stripe sheet reported an error).
  void reportError(Object error) {
    if (_alive) state = state.copyWith(error: () => error);
  }

  void setBusy(bool busy) {
    if (_alive) state = state.copyWith(busy: busy);
  }
}

/// A user-facing explanation for payment errors.
String paymentErrorText(Object error) {
  final api = ApiError.from(error);
  if (api == null) return describeError(error);
  return switch (api.code) {
    'reservation_expired' => 'The stock reservation for this order has expired. Your items are back in your cart.',
    'order_already_paid' => 'This order has already been paid.',
    'order_not_payable' => api.detail,
    'payment_provider_changed' =>
      'This order was created with a different payment provider and cannot be paid now. Cancel it and check out again.',
    'payments_unavailable' || 'payment_unavailable' => 'Payments are not available right now.',
    'no_action_required' => 'This payment is not waiting for authentication any more.',
    'payment_processing' => 'This payment is being processed and cannot be cancelled now.',
    'order_not_cancellable' => api.detail,
    _ => api.detail,
  };
}
