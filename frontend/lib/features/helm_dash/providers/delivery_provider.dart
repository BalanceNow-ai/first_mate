import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

/// Fetch a single delivery by ID.
final deliveryDetailProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, String>((ref, id) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getHelmDashDelivery(id);
});

/// Fetch all user deliveries.
final deliveryListProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getHelmDashDeliveries();
});

/// Simulated live location for the delivery vessel.
/// In production, this would connect to a WebSocket or polling endpoint.
class DeliveryLocation {
  final double lat;
  final double lng;
  final String label;

  const DeliveryLocation({
    required this.lat,
    required this.lng,
    required this.label,
  });
}

/// Simulated live position provider. Moves towards destination.
final deliveryLiveLocationProvider = FutureProvider.autoDispose
    .family<DeliveryLocation, String>((ref, deliveryId) async {
  final delivery = await ref.watch(deliveryDetailProvider(deliveryId).future);
  final coords = delivery['delivery_coordinates'] as Map<String, dynamic>?;
  final status = delivery['status'] as String? ?? 'pending';

  // Warehouse coordinates (Westhaven Marina)
  const warehouseLat = -36.8406;
  const warehouseLng = 174.7530;

  if (coords == null) {
    return const DeliveryLocation(
      lat: warehouseLat,
      lng: warehouseLng,
      label: 'Westhaven Marina (Warehouse)',
    );
  }

  final destLat = (coords['lat'] as num?)?.toDouble() ?? warehouseLat;
  final destLng = (coords['lng'] as num?)?.toDouble() ?? warehouseLng;

  // Simulate position based on delivery status
  switch (status) {
    case 'pending':
    case 'assigned':
      return const DeliveryLocation(
        lat: warehouseLat,
        lng: warehouseLng,
        label: 'At warehouse — preparing order',
      );
    case 'pickup':
      return DeliveryLocation(
        lat: warehouseLat + (destLat - warehouseLat) * 0.1,
        lng: warehouseLng + (destLng - warehouseLng) * 0.1,
        label: 'Departing warehouse',
      );
    case 'en_route':
      // Simulate midway position
      return DeliveryLocation(
        lat: warehouseLat + (destLat - warehouseLat) * 0.6,
        lng: warehouseLng + (destLng - warehouseLng) * 0.6,
        label: 'En route to delivery point',
      );
    case 'delivered':
      return DeliveryLocation(
        lat: destLat,
        lng: destLng,
        label: 'Delivered',
      );
    default:
      return const DeliveryLocation(
        lat: warehouseLat,
        lng: warehouseLng,
        label: 'Status unknown',
      );
  }
});
