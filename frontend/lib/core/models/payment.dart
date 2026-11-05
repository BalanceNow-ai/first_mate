import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

/// `POST /payments/orders/{id}/intent`: the order's card PaymentIntent (created
/// or recovered — repeating the call reuses the same intent).
class PaymentIntentInfo {
  const PaymentIntentInfo({
    required this.orderId,
    required this.provider,
    required this.paymentIntentId,
    required this.clientSecret,
    required this.status,
    required this.amountCents,
    required this.currency,
    required this.testMode,
    this.publishableKey,
    this.expiresAt,
  });

  final String orderId;

  /// `stripe` or `local` (development test provider: no real charge).
  final String provider;
  final String paymentIntentId;
  final String clientSecret;
  final String status;
  final int amountCents;
  final String currency;
  final String? publishableKey;
  final bool testMode;
  final DateTime? expiresAt;

  bool get isLocal => provider == 'local';

  factory PaymentIntentInfo.fromJson(Map<String, dynamic> json) {
    final expires = opt<String>(json, 'expires_at');
    return PaymentIntentInfo(
      orderId: req<String>(json, 'order_id'),
      provider: req<String>(json, 'provider'),
      paymentIntentId: req<String>(json, 'payment_intent_id'),
      clientSecret: req<String>(json, 'client_secret'),
      status: req<String>(json, 'status'),
      amountCents: centsFrom(json, 'amount_cents'),
      currency: opt<String>(json, 'currency') ?? 'NZD',
      publishableKey: opt<String>(json, 'publishable_key'),
      testMode: req<bool>(json, 'test_mode'),
      expiresAt: expires == null ? null : DateTime.parse(expires),
    );
  }
}

/// Outcomes the local TEST MODE provider can simulate.
enum LocalPaymentOutcome {
  succeed('succeed', 'Card succeeds'),
  decline('decline', 'Card is declined'),
  requiresAction('requires_action', 'Bank asks for authentication'),
  authenticate('authenticate', 'Complete authentication');

  const LocalPaymentOutcome(this.wire, this.label);

  final String wire;
  final String label;
}

/// `POST /payments/local/{pi}/confirm` (test mode only). It reports what the
/// signed event did; the client still re-reads the order to learn its status.
class LocalConfirmResult {
  const LocalConfirmResult({
    required this.testMode,
    required this.outcome,
    required this.eventId,
    required this.eventType,
    required this.eventOutcome,
    required this.orderId,
    required this.orderStatus,
    required this.paymentStatus,
  });

  final bool testMode;
  final String outcome;
  final String eventId;
  final String eventType;
  final String eventOutcome;
  final String orderId;
  final String orderStatus;
  final String paymentStatus;

  factory LocalConfirmResult.fromJson(Map<String, dynamic> json) => LocalConfirmResult(
        testMode: req<bool>(json, 'test_mode'),
        outcome: req<String>(json, 'outcome'),
        eventId: req<String>(json, 'event_id'),
        eventType: req<String>(json, 'event_type'),
        eventOutcome: req<String>(json, 'event_outcome'),
        orderId: req<String>(json, 'order_id'),
        orderStatus: req<String>(json, 'order_status'),
        paymentStatus: req<String>(json, 'payment_status'),
      );
}

/// A single-use Crew Rewards discount (`EntitlementOut`) offered at checkout.
class DiscountEntitlement {
  const DiscountEntitlement({
    required this.id,
    required this.code,
    required this.amountCents,
    required this.pointsCost,
    required this.status,
    required this.createdAt,
    this.orderId,
  });

  final String id;
  final String code;
  final int amountCents;
  final int pointsCost;
  final String status;
  final String? orderId;
  final DateTime createdAt;

  factory DiscountEntitlement.fromJson(Map<String, dynamic> json) => DiscountEntitlement(
        id: req<String>(json, 'id'),
        code: req<String>(json, 'code'),
        amountCents: centsFrom(json, 'amount_cents'),
        pointsCost: req<int>(json, 'points_cost'),
        status: req<String>(json, 'status'),
        orderId: opt<String>(json, 'order_id'),
        createdAt: reqDate(json, 'created_at'),
      );
}
