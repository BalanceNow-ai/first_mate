import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';

import '../helpers/fakes.dart';

void main() {
  late FakeAuthGateway gateway;
  late FakeBackend backend;
  late Dio dio;
  late int expiredCalls;

  setUp(() {
    gateway = FakeAuthGateway(token: 'token-1', userId: 'u1');
    backend = FakeBackend();
    expiredCalls = 0;
    dio = createApiDio(
      baseUrl: 'http://api.test/api/v1',
      gateway: gateway,
      adapter: backend,
      onSessionExpired: () async => expiredCalls++,
    );
  });

  test('reads the CURRENT session token for every request', () async {
    backend.json('GET /vessels/', 200, []);
    await dio.get('/vessels/');
    gateway.token = 'token-2'; // Supabase refreshed the session in the background.
    await dio.get('/vessels/');
    gateway.token = null;
    await dio.get('/vessels/');
    expect(backend.requests.map((r) => r.authorization),
        ['Bearer token-1', 'Bearer token-2', null]);
  });

  test('on 401 refreshes once and retries through the same configured Dio', () async {
    backend.on('GET /cart/', (r) => r.authorization == 'Bearer fresh'
        ? const FakeResponse(200, {'ok': true})
        : const FakeResponse(401, {'detail': 'Authentication token has expired', 'code': 'invalid_token'}));
    gateway.refreshedToken = 'fresh';

    final response = await dio.get('/cart/', options: Options(headers: {'X-Trace': 'abc'}));

    expect(response.data, {'ok': true});
    expect(gateway.refreshCalls, 1);
    final calls = backend.calls('GET /cart/');
    expect(calls, hasLength(2));
    expect(calls.last.authorization, 'Bearer fresh');
    // Retried with the original options on the configured client (same base URL / headers).
    expect(calls.last.headers['X-Trace'], 'abc');
    expect(expiredCalls, 0);
  });

  test('concurrent 401s share a single refresh', () async {
    backend.on('GET /a', (r) => r.authorization == 'Bearer fresh'
        ? const FakeResponse(200, 'a')
        : const FakeResponse(401, {'detail': 'expired', 'code': 'invalid_token'}));
    backend.on('GET /b', (r) => r.authorization == 'Bearer fresh'
        ? const FakeResponse(200, 'b')
        : const FakeResponse(401, {'detail': 'expired', 'code': 'invalid_token'}));
    gateway.refreshedToken = 'fresh';
    final results = await Future.wait([dio.get('/a'), dio.get('/b')]);
    expect(results.map((r) => r.data), ['a', 'b']);
    expect(gateway.refreshCalls, 1);
  });

  test('refresh failure ends the session and surfaces the server error', () async {
    backend.json('GET /cart/', 401, {'detail': 'Authentication token has expired', 'code': 'invalid_token'});
    gateway.refreshedToken = null;
    await expectLater(
      dio.get('/cart/'),
      throwsA(isA<DioException>().having((e) => (e.error as ApiError).code, 'code', 'invalid_token')),
    );
    expect(gateway.refreshCalls, 1);
    expect(expiredCalls, 1);
    expect(backend.calls('GET /cart/'), hasLength(1));
  });

  test('a second 401 after refreshing does not loop and signs out', () async {
    backend.json('GET /cart/', 401, {'detail': 'nope', 'code': 'invalid_token'});
    gateway.refreshedToken = 'fresh';
    await expectLater(dio.get('/cart/'), throwsA(isA<DioException>()));
    expect(backend.calls('GET /cart/'), hasLength(2));
    expect(gateway.refreshCalls, 1);
    expect(expiredCalls, 1);
  });

  test('403 and unauthenticated requests are not refreshed', () async {
    backend.json('GET /auth/me', 403, fixture('error_profile_not_provisioned'));
    await expectLater(
      dio.get('/auth/me'),
      throwsA(isA<DioException>().having((e) => (e.error as ApiError).code, 'code', 'profile_not_provisioned')),
    );
    gateway.token = null;
    backend.json('GET /cart/', 401, fixture('error_unauthenticated'));
    await expectLater(dio.get('/cart/'), throwsA(isA<DioException>()));
    expect(gateway.refreshCalls, 0);
    expect(expiredCalls, 0);
  });

  test('public requests can skip the Authorization header', () async {
    backend.json('GET /config/public', 200, fixture('config_public'));
    await dio.get('/config/public', options: Options(extra: {AuthInterceptor.skipAuthKey: true}));
    expect(backend.requests.single.authorization, isNull);
  });
}
