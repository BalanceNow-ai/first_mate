import 'package:helm_marine/core/models/json.dart';

/// The local Helm profile (`UserResponse`). Identity (id, email) comes from the
/// verified token on the server; the role is server-held and read-only here.
class User {
  const User({
    required this.id,
    required this.email,
    required this.fullName,
    required this.phone,
    required this.role,
    required this.createdAt,
  });

  final String id;
  final String email;
  final String? fullName;
  final String? phone;

  /// `customer` / `operator` / `dispatcher` / `admin`.
  final String role;
  final DateTime createdAt;

  /// Name to greet the user with.
  String get displayName =>
      (fullName != null && fullName!.trim().isNotEmpty) ? fullName!.trim() : email;

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: req<String>(json, 'id'),
        email: req<String>(json, 'email'),
        fullName: opt<String>(json, 'full_name'),
        phone: opt<String>(json, 'phone'),
        role: req<String>(json, 'role'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `ProvisionResponse`: the profile plus whether this call created it.
class ProvisionResult {
  const ProvisionResult({required this.user, required this.created});

  final User user;
  final bool created;

  factory ProvisionResult.fromJson(Map<String, dynamic> json) => ProvisionResult(
        user: User.fromJson(json),
        created: opt<bool>(json, 'created') ?? false,
      );
}

/// `UserUpdate` payload (PATCH /users/me). Only name and phone are editable.
class UserUpdate {
  const UserUpdate({this.fullName, this.phone});

  final String? fullName;
  final String? phone;

  Map<String, dynamic> toJson() => {'full_name': fullName, 'phone': phone};
}
