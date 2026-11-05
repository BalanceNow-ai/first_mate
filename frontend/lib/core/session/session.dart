import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/user.dart';

/// Id of the signed-in, provisioned user (null otherwise).
final currentUserIdProvider = Provider<String?>((ref) {
  return ref.watch(authControllerProvider.select((s) => s.isSignedIn ? s.userId : null));
});

/// The signed-in user's profile (null otherwise).
final currentUserProvider = Provider<User?>((ref) {
  return ref.watch(authControllerProvider.select((s) => s.user));
});

/// API access for **user-scoped** data.
///
/// Every provider that caches per-user data (vessels, cart, orders, checklists,
/// rewards, chat, deliveries, the selected vessel...) must obtain the API through
/// `ref.watch(userApiProvider)`. A new instance is created whenever the signed-in
/// user changes (sign-out, sign-in as someone else, a different session arriving
/// via `onAuthStateChange`), so Riverpod rebuilds or disposes every dependant and
/// no data from one account is ever shown to another.
final userApiProvider = Provider<ApiService>((ref) {
  ref.watch(currentUserIdProvider);
  return ApiService(ref.watch(dioProvider));
});

/// Thrown by user-scoped providers when read while nobody is signed in.
class SignedOutException implements Exception {
  const SignedOutException();

  @override
  String toString() => 'You are signed out.';
}

/// Returns the signed-in user's id or throws [SignedOutException]; watching it
/// ties the calling provider's lifetime to the current user.
String requireUserId(Ref ref) {
  final id = ref.watch(currentUserIdProvider);
  if (id == null) throw const SignedOutException();
  return id;
}
