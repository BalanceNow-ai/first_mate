import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/user.dart';

void main() {
  group('User', () {
    test('fromJson creates User correctly', () {
      final json = {
        'id': 'user-123',
        'email': 'skipper@helmmarine.co.nz',
        'full_name': 'Test Skipper',
        'phone': '+64211234567',
        'avatar_url': null,
        'role': 'customer',
        'created_at': '2026-01-01T00:00:00.000Z',
      };

      final user = User.fromJson(json);

      expect(user.id, 'user-123');
      expect(user.email, 'skipper@helmmarine.co.nz');
      expect(user.fullName, 'Test Skipper');
      expect(user.phone, '+64211234567');
      expect(user.avatarUrl, isNull);
      expect(user.role, 'customer');
    });

    test('fromJson defaults role to customer when missing', () {
      final json = {
        'id': 'user-456',
        'email': 'test@test.com',
        'created_at': '2026-01-01T00:00:00.000Z',
      };

      final user = User.fromJson(json);
      expect(user.role, 'customer');
    });

    test('toJson produces correct map', () {
      final user = User(
        id: 'user-789',
        email: 'test@helmmarine.co.nz',
        fullName: 'John Doe',
        createdAt: DateTime.utc(2026, 1, 1),
      );

      final json = user.toJson();
      expect(json['id'], 'user-789');
      expect(json['email'], 'test@helmmarine.co.nz');
      expect(json['full_name'], 'John Doe');
    });
  });
}
