import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/session/session.dart';

/// The fields of a Helm Dash delivery (`TrackingOut`) the home screen links to.
class DeliverySummary {
  const DeliverySummary({
    required this.id,
    required this.orderNumber,
    required this.status,
    required this.statusLabel,
    this.estimatedDeliveryMinutes,
  });

  final String id;
  final String orderNumber;
  final String status;
  final String statusLabel;
  final int? estimatedDeliveryMinutes;

  static const _finished = {'delivered', 'failed', 'cancelled'};

  bool get isActive => !_finished.contains(status);

  factory DeliverySummary.fromJson(Map<String, dynamic> json) => DeliverySummary(
        id: req<String>(json, 'id'),
        orderNumber: req<String>(json, 'order_number'),
        status: req<String>(json, 'status'),
        statusLabel: req<String>(json, 'status_label'),
        estimatedDeliveryMinutes: opt<int>(json, 'estimated_delivery_minutes'),
      );
}

/// The signed-in user's in-progress Helm Dash delivery (most recent), if any.
final activeDeliveryProvider = FutureProvider.autoDispose<DeliverySummary?>((ref) async {
  requireUserId(ref);
  final dio = ref.watch(dioProvider);
  try {
    final response = await dio.get('/helm-dash/deliveries');
    for (final d in response.data as List) {
      final delivery = DeliverySummary.fromJson((d as Map).cast<String, dynamic>());
      if (delivery.isActive) return delivery;
    }
    return null;
  } on DioException catch (e) {
    throw ApiError.from(e)!;
  }
});
