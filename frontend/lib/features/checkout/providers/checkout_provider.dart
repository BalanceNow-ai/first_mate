import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/orders/data/commerce_api.dart';

/// Delivery options for the *current* cart (re-fetched whenever the cart changes).
final deliveryOptionsProvider = FutureProvider.autoDispose<DeliveryOptions>((ref) async {
  // Depend on the cart so availability (dangerous goods, weights, totals) follows it.
  await ref.watch(cartProvider.future);
  return ref.watch(commerceApiProvider).deliveryOptions();
});

/// Enabled Helm Dash operating areas (public).
final helmDashAreasProvider = FutureProvider.autoDispose<List<OperatingAreaSummary>>((ref) {
  return ref.watch(commerceApiProvider).helmDashAreas();
});

/// The user's unused Crew Rewards discounts.
final issuedEntitlementsProvider = FutureProvider.autoDispose<List<DiscountEntitlement>>((ref) {
  return ref.watch(commerceApiProvider).issuedEntitlements();
});

/// The clock used for quote expiry (overridable in tests).
final checkoutClockProvider = Provider<DateTime Function()>((ref) => DateTime.now);

/// Error codes that mean the delivery quote must be fetched again.
const requoteCodes = {
  'quote_cart_changed',
  'quote_expired',
  'quote_used',
  'quote_not_found',
  'quote_required',
  'quote_type_mismatch',
  'quote_destination_mismatch',
};

/// A fresh Idempotency-Key: 8-100 chars of `A-Z a-z 0-9 _ - : .`.
String newIdempotencyKey([Random? random]) {
  final r = random ?? Random.secure();
  final a = r.nextInt(1 << 32).toRadixString(36);
  final b = r.nextInt(1 << 32).toRadixString(36);
  return 'checkout-${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-$a$b';
}

class CheckoutState {
  const CheckoutState({
    this.deliveryType,
    this.quote,
    this.quoting = false,
    this.quoteError,
    this.entitlementId,
    this.preview,
    this.previewing = false,
    this.previewError,
    this.placing = false,
    this.placeError,
    this.attemptKey,
    this.orderId,
  });

  final String? deliveryType;
  final DeliveryQuote? quote;
  final bool quoting;
  final Object? quoteError;
  final String? entitlementId;
  final CheckoutPreview? preview;
  final bool previewing;
  final Object? previewError;
  final bool placing;
  final Object? placeError;

  /// The Idempotency-Key of this checkout attempt. Generated on the first
  /// "Place order" and kept for every retry until a new attempt starts.
  final String? attemptKey;

  /// The order created by this attempt.
  final String? orderId;

  CheckoutState copyWith({
    String? Function()? deliveryType,
    DeliveryQuote? Function()? quote,
    bool? quoting,
    Object? Function()? quoteError,
    String? Function()? entitlementId,
    CheckoutPreview? Function()? preview,
    bool? previewing,
    Object? Function()? previewError,
    bool? placing,
    Object? Function()? placeError,
    String? Function()? attemptKey,
    String? Function()? orderId,
  }) =>
      CheckoutState(
        deliveryType: deliveryType == null ? this.deliveryType : deliveryType(),
        quote: quote == null ? this.quote : quote(),
        quoting: quoting ?? this.quoting,
        quoteError: quoteError == null ? this.quoteError : quoteError(),
        entitlementId: entitlementId == null ? this.entitlementId : entitlementId(),
        preview: preview == null ? this.preview : preview(),
        previewing: previewing ?? this.previewing,
        previewError: previewError == null ? this.previewError : previewError(),
        placing: placing ?? this.placing,
        placeError: placeError == null ? this.placeError : placeError(),
        attemptKey: attemptKey == null ? this.attemptKey : attemptKey(),
        orderId: orderId == null ? this.orderId : orderId(),
      );
}

/// Server-driven checkout. The client never prices anything: options, quotes,
/// totals and the order all come from the API. Kept alive for the signed-in
/// user so leaving and re-opening checkout (or retrying after a lost response)
/// keeps the same attempt and Idempotency-Key.
final checkoutProvider = NotifierProvider<CheckoutController, CheckoutState>(CheckoutController.new);

class CheckoutController extends Notifier<CheckoutState> {
  @override
  CheckoutState build() {
    ref.watch(currentUserIdProvider);
    return const CheckoutState();
  }

  CommerceApi get _api => ref.read(commerceApiProvider);

  void selectDelivery(String type) {
    if (state.deliveryType == type) return;
    state = state.copyWith(
      deliveryType: () => type,
      quote: () => null,
      quoteError: () => null,
      preview: () => null,
      previewError: () => null,
      placeError: () => null,
    );
  }

  /// Drops the current quote (address / pin changed, or the server refused it).
  void clearQuote() {
    state = state.copyWith(quote: () => null, preview: () => null, previewError: () => null);
  }

  Future<DeliveryQuote?> _quote(Future<DeliveryQuote> Function() request) async {
    if (state.quoting) return null;
    state = state.copyWith(
      quoting: true,
      quote: () => null,
      quoteError: () => null,
      preview: () => null,
      previewError: () => null,
      placeError: () => null,
    );
    try {
      final quote = await request();
      if (ref.mounted) state = state.copyWith(quoting: false, quote: () => quote);
      return quote;
    } catch (e) {
      if (ref.mounted) state = state.copyWith(quoting: false, quoteError: () => e);
      return null;
    }
  }

  Future<DeliveryQuote?> quoteCourier({required String postcode, String? city, String? suburb}) =>
      _quote(() => _api.courierQuote(postcode: postcode, city: city, suburb: suburb));

  Future<DeliveryQuote?> quoteHelmDash({required double lat, required double lng, String? locationName}) =>
      _quote(() => _api.helmDashQuote(lat: lat, lng: lng, locationName: locationName));

  void selectEntitlement(String? id) {
    state = state.copyWith(entitlementId: () => id, preview: () => null, previewError: () => null);
  }

  /// `POST /orders/checkout/preview` for [request].
  Future<CheckoutPreview?> preview(CheckoutRequest request) async {
    final quote = state.quote;
    if (quote != null && quote.isExpired(ref.read(checkoutClockProvider)())) {
      state = state.copyWith(previewError: () => _quoteExpired, preview: () => null);
      return null;
    }
    state = state.copyWith(previewing: true, previewError: () => null);
    try {
      final preview = await _api.previewCheckout(request);
      if (ref.mounted) state = state.copyWith(previewing: false, preview: () => preview);
      return preview;
    } catch (e) {
      if (!ref.mounted) return null;
      state = state.copyWith(previewing: false, previewError: () => e, preview: () => null);
      _afterServerError(e);
      return null;
    }
  }

  static const _quoteExpired = ApiError(
    statusCode: 409,
    code: 'quote_expired',
    detail: 'This delivery quote has expired. Please get a new quote.',
  );

  void _afterServerError(Object e) {
    final api = ApiError.from(e);
    if (api != null && requoteCodes.contains(api.code)) {
      state = state.copyWith(quote: () => null);
    }
  }

  /// Places the order once. Double taps while in flight are ignored and every
  /// retry of this attempt reuses the same Idempotency-Key, so a lost response
  /// can never create a second order.
  Future<Order?> placeOrder(CheckoutRequest request) async {
    if (state.placing) return null;
    final quote = state.quote;
    if (quote != null && quote.isExpired(ref.read(checkoutClockProvider)())) {
      state = state.copyWith(placeError: () => _quoteExpired, quote: () => null);
      return null;
    }
    final key = state.attemptKey ?? newIdempotencyKey();
    state = state.copyWith(placing: true, placeError: () => null, attemptKey: () => key);
    try {
      final order = await _api.checkout(request, idempotencyKey: key);
      if (!ref.mounted) return order;
      state = state.copyWith(placing: false, orderId: () => order.id);
      // The server moved the cart into the order.
      ref.invalidate(cartProvider);
      return order;
    } catch (e) {
      if (!ref.mounted) return null;
      state = state.copyWith(placing: false, placeError: () => e);
      _afterServerError(e);
      return null;
    }
  }

  /// Starts a new checkout attempt (after the order was paid or cancelled).
  void reset() => state = const CheckoutState();
}
