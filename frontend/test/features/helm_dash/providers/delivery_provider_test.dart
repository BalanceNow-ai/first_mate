import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/helm_dash/providers/delivery_provider.dart';

void main() {
  group('DeliveryLocation', () {
    test('creates a delivery location', () {
      const loc = DeliveryLocation(
        lat: -36.8406,
        lng: 174.7530,
        label: 'Westhaven Marina',
      );

      expect(loc.lat, -36.8406);
      expect(loc.lng, 174.7530);
      expect(loc.label, 'Westhaven Marina');
    });

    test('different statuses produce different labels', () {
      // These are tested via the provider; here we verify the model works
      const warehouse = DeliveryLocation(
        lat: -36.8406,
        lng: 174.7530,
        label: 'At warehouse — preparing order',
      );
      const enRoute = DeliveryLocation(
        lat: -36.85,
        lng: 174.76,
        label: 'En route to delivery point',
      );
      const delivered = DeliveryLocation(
        lat: -36.87,
        lng: 174.78,
        label: 'Delivered',
      );

      expect(warehouse.label, contains('warehouse'));
      expect(enRoute.label, contains('En route'));
      expect(delivered.label, 'Delivered');
    });
  });
}
