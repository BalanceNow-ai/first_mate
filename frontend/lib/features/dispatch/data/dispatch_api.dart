import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/orders/data/api_call.dart';

/// Staff API: Helm Dash dispatch, operator jobs, administration and staff
/// order handling. Authorization is the server's (403 `forbidden`); the role
/// checks in the UI only decide what to show.
final staffApiProvider = Provider<StaffApi>((ref) {
  ref.watch(currentUserIdProvider);
  return StaffApi(ref.watch(dioProvider));
});

/// Filters for `GET /dispatch/deliveries`.
class DeliveryFilter {
  const DeliveryFilter({this.status, this.areaId, this.activeOnly = true});

  final String? status;
  final String? areaId;
  final bool activeOnly;

  @override
  bool operator ==(Object other) =>
      other is DeliveryFilter && other.status == status && other.areaId == areaId && other.activeOnly == activeOnly;

  @override
  int get hashCode => Object.hash(status, areaId, activeOnly);
}

/// Filters for `GET /orders/admin/all`.
class StaffOrderFilter {
  const StaffOrderFilter({this.status, this.paymentStatus, this.deliveryType, this.orderNumber, this.page = 1});

  final String? status;
  final String? paymentStatus;
  final String? deliveryType;
  final String? orderNumber;
  final int page;

  StaffOrderFilter copyWith({
    String? Function()? status,
    String? Function()? paymentStatus,
    String? Function()? deliveryType,
    String? Function()? orderNumber,
    int? page,
  }) =>
      StaffOrderFilter(
        status: status == null ? this.status : status(),
        paymentStatus: paymentStatus == null ? this.paymentStatus : paymentStatus(),
        deliveryType: deliveryType == null ? this.deliveryType : deliveryType(),
        orderNumber: orderNumber == null ? this.orderNumber : orderNumber(),
        page: page ?? this.page,
      );

  @override
  bool operator ==(Object other) =>
      other is StaffOrderFilter &&
      other.status == status &&
      other.paymentStatus == paymentStatus &&
      other.deliveryType == deliveryType &&
      other.orderNumber == orderNumber &&
      other.page == page;

  @override
  int get hashCode => Object.hash(status, paymentStatus, deliveryType, orderNumber, page);
}

class StaffApi {
  StaffApi(this._dio);

  final Dio _dio;

  // --- Dispatcher ---

  Future<List<DispatchDelivery>> deliveries(DeliveryFilter filter) => apiCall(
        () => _dio.get('/dispatch/deliveries', queryParameters: {
          'status': ?filter.status,
          'area_id': ?filter.areaId,
          if (filter.activeOnly) 'active_only': true,
        }),
        (d) => [for (final x in asMapList(d)) DispatchDelivery.fromJson(x)],
      );

  Future<DispatchDelivery> delivery(String id) =>
      apiCall(() => _dio.get('/dispatch/deliveries/$id'), (d) => DispatchDelivery.fromJson(asMap(d)));

  Future<DispatchDelivery> assign(String id, String operatorId, {String? note}) => apiCall(
        () => _dio.post('/dispatch/deliveries/$id/assign', data: {
          'operator_id': operatorId,
          if (note != null && note.isNotEmpty) 'note': note,
        }),
        (d) => DispatchDelivery.fromJson(asMap(d)),
      );

  Future<DispatchDelivery> cancelDelivery(String id, {String? reason}) => apiCall(
        () => _dio.post('/dispatch/deliveries/$id/cancel', data: {'reason': ?reason}),
        (d) => DispatchDelivery.fromJson(asMap(d)),
      );

  Future<DispatchDelivery> failDelivery(String id, {String? reason}) => apiCall(
        () => _dio.post('/dispatch/deliveries/$id/fail', data: {'reason': ?reason}),
        (d) => DispatchDelivery.fromJson(asMap(d)),
      );

  Future<List<OperatorProfile>> operators({String? areaId, bool? active, bool? online}) => apiCall(
        () => _dio.get('/dispatch/operators', queryParameters: {
          'area_id': ?areaId,
          'active': ?active,
          'online': ?online,
        }),
        (d) => [for (final x in asMapList(d)) OperatorProfile.fromJson(x)],
      );

  Future<List<OperatingArea>> areas() => apiCall(
        () => _dio.get('/dispatch/areas'),
        (d) => [for (final x in asMapList(d)) OperatingArea.fromJson(x)],
      );

  // --- Admin ---

  Future<OperatingArea> createArea({
    required String id,
    required String name,
    required double centerLat,
    required double centerLng,
    required double radiusNm,
    required bool enabled,
  }) =>
      apiCall(
        () => _dio.post('/dispatch/areas', data: {
          'id': id,
          'name': name,
          'center_lat': centerLat,
          'center_lng': centerLng,
          'radius_nm': radiusNm,
          'enabled': enabled,
        }),
        (d) => OperatingArea.fromJson(asMap(d)),
      );

  Future<OperatingArea> updateArea(String id, Map<String, dynamic> changes) => apiCall(
        () => _dio.patch('/dispatch/areas/$id', data: changes),
        (d) => OperatingArea.fromJson(asMap(d)),
      );

  Future<OperatorProfile> createOperator({
    required String userId,
    required String displayName,
    required String areaId,
    String? vesselName,
    String? certificationReference,
  }) =>
      apiCall(
        () => _dio.post('/dispatch/operators', data: {
          'user_id': userId,
          'display_name': displayName,
          'area_id': areaId,
          if (vesselName != null && vesselName.isNotEmpty) 'vessel_name': vesselName,
          if (certificationReference != null && certificationReference.isNotEmpty)
            'certification_reference': certificationReference,
        }),
        (d) => OperatorProfile.fromJson(asMap(d)),
      );

  Future<OperatorProfile> setOperatorActive(String userId, bool active) => apiCall(
        () => _dio.post('/dispatch/operators/$userId/${active ? 'activate' : 'deactivate'}'),
        (d) => OperatorProfile.fromJson(asMap(d)),
      );

  Future<List<Payout>> payouts({String? status}) => apiCall(
        () => _dio.get('/dispatch/payouts', queryParameters: {'status': ?status}),
        (d) => [for (final x in asMapList(d)) Payout.fromJson(x)],
      );

  Future<Payout> approvePayout(String id) =>
      apiCall(() => _dio.post('/dispatch/payouts/$id/approve'), (d) => Payout.fromJson(asMap(d)));

  Future<Reconciliation> reconciliation({String? period}) => apiCall(
        () => _dio.get('/dispatch/reconciliation', queryParameters: {'period': ?period}),
        (d) => Reconciliation.fromJson(asMap(d)),
      );

  // --- Operator ---

  Future<OperatorProfile> myOperatorProfile() =>
      apiCall(() => _dio.get('/dispatch/me'), (d) => OperatorProfile.fromJson(asMap(d)));

  Future<OperatorProfile> setAvailability(bool online) => apiCall(
        () => _dio.put('/dispatch/me/availability', data: {'is_online': online}),
        (d) => OperatorProfile.fromJson(asMap(d)),
      );

  Future<List<DispatchDelivery>> myJobs({bool includeFinished = false}) => apiCall(
        () => _dio.get('/dispatch/jobs', queryParameters: {if (includeFinished) 'include_finished': true}),
        (d) => [for (final x in asMapList(d)) DispatchDelivery.fromJson(x)],
      );

  Future<DispatchDelivery> myJob(String id) =>
      apiCall(() => _dio.get('/dispatch/jobs/$id'), (d) => DispatchDelivery.fromJson(asMap(d)));

  Future<DispatchDelivery> acceptJob(String id) =>
      apiCall(() => _dio.post('/dispatch/jobs/$id/accept'), (d) => DispatchDelivery.fromJson(asMap(d)));

  Future<DispatchDelivery> declineJob(String id, {String? reason}) => apiCall(
        () => _dio.post('/dispatch/jobs/$id/decline', data: {'reason': ?reason}),
        (d) => DispatchDelivery.fromJson(asMap(d)),
      );

  Future<DispatchDelivery> setJobStatus(String id, String status, {String? note}) => apiCall(
        () => _dio.post('/dispatch/jobs/$id/status', data: {
          'status': status,
          if (note != null && note.isNotEmpty) 'note': note,
        }),
        (d) => DispatchDelivery.fromJson(asMap(d)),
      );

  /// Posts a reading taken from the device geolocation API.
  Future<LocationReceipt> reportLocation(
    String id, {
    required double lat,
    required double lng,
    required DateTime recordedAt,
    double? accuracyM,
    double? headingDeg,
    double? speedKnots,
  }) =>
      apiCall(
        () => _dio.post('/dispatch/jobs/$id/location', data: {
          'lat': lat,
          'lng': lng,
          'recorded_at': recordedAt.toUtc().toIso8601String(),
          'accuracy_m': ?accuracyM,
          'heading_deg': ?headingDeg,
          'speed_knots': ?speedKnots,
        }),
        (d) => LocationReceipt.fromJson(asMap(d)),
      );

  // --- Staff orders ---

  Future<OrderPage> staffOrders(StaffOrderFilter filter, {int pageSize = 25}) => apiCall(
        () => _dio.get('/orders/admin/all', queryParameters: {
          'status': ?filter.status,
          'payment_status': ?filter.paymentStatus,
          'delivery_type': ?filter.deliveryType,
          if (filter.orderNumber != null && filter.orderNumber!.isNotEmpty) 'order_number': filter.orderNumber,
          'page': filter.page,
          'page_size': pageSize,
        }),
        (d) => OrderPage.fromJson(asMap(d)),
      );

  Future<Order> staffOrder(String id) =>
      apiCall(() => _dio.get('/orders/admin/$id'), (d) => Order.fromJson(asMap(d)));

  Future<Order> updateFulfilment(String id, String status, {String? trackingNumber, String? courier}) =>
      apiCall(
        () => _dio.patch('/orders/$id/fulfilment', data: {
          'status': status,
          if (trackingNumber != null && trackingNumber.isNotEmpty) 'tracking_number': trackingNumber,
          if (courier != null && courier.isNotEmpty) 'courier': courier,
        }),
        (d) => Order.fromJson(asMap(d)),
      );

  Future<Shipment> createShipment(String id) =>
      apiCall(() => _dio.post('/orders/$id/shipment'), (d) => Shipment.fromJson(asMap(d)));

  /// Admin refund. [idempotencyKey] identifies one refund request: repeating
  /// it never refunds twice (the server answers `status: duplicate_request`).
  Future<RefundResult> refund(
    String id, {
    required int amountCents,
    required String reason,
    required String idempotencyKey,
  }) =>
      apiCall(
        () => _dio.post('/orders/$id/refund',
            data: {'amount_cents': amountCents, 'reason': reason},
            options: Options(headers: {'Idempotency-Key': idempotencyKey})),
        (d) => RefundResult.fromJson(asMap(d)),
      );
}
