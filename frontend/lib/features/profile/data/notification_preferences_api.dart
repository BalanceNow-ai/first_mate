import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/notification_preferences.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/products/data/api_call.dart';

final notificationPreferencesApiProvider = Provider<NotificationPreferencesApi>((ref) {
  ref.watch(currentUserIdProvider);
  return NotificationPreferencesApi(ref.watch(dioProvider));
});

/// `GET/PUT /notifications/preferences`.
class NotificationPreferencesApi {
  NotificationPreferencesApi(this._dio);

  final Dio _dio;

  Future<NotificationPreferences> get() => apiCall(
        () => _dio.get('/notifications/preferences'),
        (d) => NotificationPreferences.fromJson(asMap(d)),
      );

  /// Sends only [changes] (wire field → value); the server keeps the rest.
  Future<NotificationPreferences> update(Map<String, bool> changes) => apiCall(
        () => _dio.put('/notifications/preferences', data: changes),
        (d) => NotificationPreferences.fromJson(asMap(d)),
      );
}

/// The signed-in user's notification preferences. Changes are optimistic and
/// rolled back when the server refuses them.
final notificationPreferencesProvider =
    AsyncNotifierProvider.autoDispose<NotificationPreferencesNotifier, NotificationPreferences>(
        NotificationPreferencesNotifier.new);

class NotificationPreferencesNotifier extends AsyncNotifier<NotificationPreferences> {
  @override
  Future<NotificationPreferences> build() {
    final api = ref.watch(notificationPreferencesApiProvider);
    requireUserId(ref);
    return api.get();
  }

  Future<void> set(String field, bool value) async {
    final before = state.value;
    if (before == null) return;
    state = AsyncData(before.withValue(field, value));
    try {
      final saved = await ref.read(notificationPreferencesApiProvider).update({field: value});
      if (ref.mounted) state = AsyncData(saved);
    } catch (_) {
      if (ref.mounted) state = AsyncData(before);
      rethrow;
    }
  }
}
