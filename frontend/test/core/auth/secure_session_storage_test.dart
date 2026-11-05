import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/secure_session_storage.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('session is written to, read from and removed from secure storage', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final store = SecureSessionStorage();
    expect(await store.hasAccessToken(), isFalse);
    await store.persistSession('{"access_token":"a","refresh_token":"r"}');
    expect(await store.hasAccessToken(), isTrue);
    expect(await store.accessToken(), contains('refresh_token'));
    await store.removePersistedSession();
    expect(await store.hasAccessToken(), isFalse);
    expect(SecureSessionStorage.applies, isTrue); // VM tests run as a native platform
  });
}
