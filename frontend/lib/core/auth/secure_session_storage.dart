import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

/// Persists the Supabase session (including the long-lived refresh token) in the
/// platform keystore — Keychain on iOS/macOS (not included in backups), the Android
/// Keystore-backed encrypted store — instead of plain SharedPreferences.
///
/// Web keeps supabase_flutter's default browser storage (there is no stronger
/// primitive available to a web page).
class SecureSessionStorage extends LocalStorage {
  SecureSessionStorage({FlutterSecureStorage? storage, this.key = supabasePersistSessionKey})
      : _storage = storage ??
            const FlutterSecureStorage(
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
              mOptions: MacOsOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
            );

  final FlutterSecureStorage _storage;
  final String key;

  /// Secure storage applies on native platforms only.
  static bool get applies => !kIsWeb;

  @override
  Future<void> initialize() async {}

  @override
  Future<bool> hasAccessToken() => _storage.containsKey(key: key);

  @override
  Future<String?> accessToken() => _storage.read(key: key);

  @override
  Future<void> removePersistedSession() => _storage.delete(key: key);

  @override
  Future<void> persistSession(String persistSessionString) =>
      _storage.write(key: key, value: persistSessionString);
}
