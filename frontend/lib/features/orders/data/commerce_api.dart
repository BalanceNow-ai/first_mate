import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/orders/data/api_call.dart';

/// Customer commerce API: delivery options and quotes, checkout, orders,
/// payments and Helm Dash tracking. A new instance per signed-in user, so
/// every dependant provider resets when the user changes.
final commerceApiProvider = Provider<CommerceApi>((ref) {
  ref.watch(currentUserIdProvider);
  return CommerceApi(ref.watch(dioProvider));
});

class CommerceApi {
  CommerceApi(this._dio);

  final Dio _dio;

  // --- Delivery ---

  Future<DeliveryOptions> deliveryOptions() =>
      apiCall(() => _dio.get('/shipping/options'), (d) => DeliveryOptions.fromJson(asMap(d)));

  Future<DeliveryQuote> courierQuote({required String postcode, String? city, String? suburb}) => apiCall(
        () => _dio.post('/shipping/quotes', data: {
          'delivery_type': DeliveryType.courier,
          'destination': {
            'postcode': postcode,
            if (city != null && city.isNotEmpty) 'city': city,
            if (suburb != null && suburb.isNotEmpty) 'suburb': suburb,
          },
        }),
        (d) => DeliveryQuote.fromJson(asMap(d)),
      );

  Future<DeliveryQuote> helmDashQuote({required double lat, required double lng, String? locationName}) =>
      apiCall(
        () => _dio.post('/shipping/quotes', data: {
          'delivery_type': DeliveryType.helmDash,
          'destination': {
            'lat': lat,
            'lng': lng,
            if (locationName != null && locationName.isNotEmpty) 'location_name': locationName,
          },
        }),
        (d) => DeliveryQuote.fromJson(asMap(d)),
      );

  /// Enabled Helm Dash operating areas (public).
  Future<List<OperatingAreaSummary>> helmDashAreas() => apiCall(
        () => _dio.get('/helm-dash/areas'),
        (d) => [for (final a in asMapList(d)) OperatingAreaSummary.fromJson(a)],
      );

  // --- Checkout ---

  Future<CheckoutPreview> previewCheckout(CheckoutRequest request) => apiCall(
        () => _dio.post('/orders/checkout/preview', data: request.toJson()),
        (d) => CheckoutPreview.fromJson(asMap(d)),
      );

  /// Creates the order (201) or returns the order already created with
  /// [idempotencyKey] (200).
  Future<Order> checkout(CheckoutRequest request, {required String idempotencyKey}) => apiCall(
        () => _dio.post('/orders/checkout',
            data: request.toJson(), options: Options(headers: {'Idempotency-Key': idempotencyKey})),
        (d) => Order.fromJson(asMap(d)),
      );

  Future<List<DiscountEntitlement>> issuedEntitlements() => apiCall(
        () => _dio.get('/loyalty/entitlements', queryParameters: {'status': 'issued'}),
        (d) => [for (final e in asMapList(d)) DiscountEntitlement.fromJson(e)],
      );

  // --- Orders ---

  Future<OrderPage> orders({int page = 1, int pageSize = 20}) => apiCall(
        () => _dio.get('/orders/', queryParameters: {'page': page, 'page_size': pageSize}),
        (d) => OrderPage.fromJson(asMap(d)),
      );

  Future<Order> order(String id) => apiCall(() => _dio.get('/orders/$id'), (d) => Order.fromJson(asMap(d)));

  Future<Order> cancelOrder(String id) =>
      apiCall(() => _dio.post('/orders/$id/cancel'), (d) => Order.fromJson(asMap(d)));

  // --- Payments ---

  /// Creates or recovers (reuses) the order's card PaymentIntent.
  Future<PaymentIntentInfo> paymentIntent(String orderId) => apiCall(
        () => _dio.post('/payments/orders/$orderId/intent', data: {'payment_method': 'card'}),
        (d) => PaymentIntentInfo.fromJson(asMap(d)),
      );

  /// TEST MODE only: simulate the card outcome through the signed webhook path.
  Future<LocalConfirmResult> confirmLocalPayment(String paymentIntentId, LocalPaymentOutcome outcome) =>
      apiCall(
        () => _dio.post('/payments/local/$paymentIntentId/confirm', data: {'outcome': outcome.wire}),
        (d) => LocalConfirmResult.fromJson(asMap(d)),
      );

  // --- Helm Dash tracking ---

  Future<List<DeliveryTracking>> myDeliveries() => apiCall(
        () => _dio.get('/helm-dash/deliveries'),
        (d) => [for (final t in asMapList(d)) DeliveryTracking.fromJson(t)],
      );

  Future<DeliveryTracking> delivery(String id) =>
      apiCall(() => _dio.get('/helm-dash/deliveries/$id'), (d) => DeliveryTracking.fromJson(asMap(d)));
}
