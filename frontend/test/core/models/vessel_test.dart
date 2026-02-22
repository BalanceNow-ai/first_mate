import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/vessel.dart';

void main() {
  group('Vessel', () {
    final sampleJson = {
      'id': 'vessel-001',
      'user_id': 'user-123',
      'name': 'Sea Breeze',
      'make': 'Stabicraft',
      'model': '1850 Fisher',
      'year': 2022,
      'hull_material': 'Aluminium',
      'length_ft': 18.5,
      'engine_type': 'Outboard',
      'engine_make': 'Yamaha',
      'engine_model': 'F115',
      'image_url': null,
      'is_primary': true,
      'created_at': '2026-01-15T10:30:00.000Z',
    };

    test('fromJson creates Vessel correctly', () {
      final vessel = Vessel.fromJson(sampleJson);

      expect(vessel.id, 'vessel-001');
      expect(vessel.name, 'Sea Breeze');
      expect(vessel.make, 'Stabicraft');
      expect(vessel.model, '1850 Fisher');
      expect(vessel.year, 2022);
      expect(vessel.hullMaterial, 'Aluminium');
      expect(vessel.lengthFt, 18.5);
      expect(vessel.engineType, 'Outboard');
      expect(vessel.engineMake, 'Yamaha');
      expect(vessel.engineModel, 'F115');
      expect(vessel.isPrimary, true);
    });

    test('fromJson handles missing optional fields', () {
      final minimalJson = {
        'id': 'vessel-002',
        'user_id': 'user-123',
        'name': 'Minimal Boat',
        'make': 'Generic',
        'model': 'Basic',
        'created_at': '2026-01-15T10:30:00.000Z',
      };

      final vessel = Vessel.fromJson(minimalJson);

      expect(vessel.year, isNull);
      expect(vessel.hullMaterial, isNull);
      expect(vessel.lengthFt, isNull);
      expect(vessel.engineType, isNull);
      expect(vessel.isPrimary, false);
    });

    test('toJson produces correct map for API submission', () {
      final vessel = Vessel.fromJson(sampleJson);
      final json = vessel.toJson();

      expect(json['name'], 'Sea Breeze');
      expect(json['make'], 'Stabicraft');
      expect(json['model'], '1850 Fisher');
      expect(json['year'], 2022);
      expect(json['is_primary'], true);
      // toJson should not include id/user_id (server-managed)
      expect(json.containsKey('id'), false);
      expect(json.containsKey('user_id'), false);
    });

    test('copyWith creates modified copy', () {
      final vessel = Vessel.fromJson(sampleJson);
      final modified = vessel.copyWith(name: 'New Name', year: 2025);

      expect(modified.name, 'New Name');
      expect(modified.year, 2025);
      expect(modified.make, vessel.make); // Unchanged
      expect(modified.id, vessel.id); // Preserved
    });
  });
}
