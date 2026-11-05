import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/auth/auth_gateway.dart';
import 'package:helm_marine/core/config/app_config.dart';

/// Loads a captured server payload from `test/fixtures/api/<name>.json`
/// (written by `scripts/capture_api_fixtures.py` from the real API).
dynamic fixture(String name) =>
    jsonDecode(File('test/fixtures/api/$name.json').readAsStringSync());

Map<String, dynamic> fixtureMap(String name) => (fixture(name) as Map).cast<String, dynamic>();

final testConfig = AppConfig.resolve(
  isRelease: false,
  apiBaseUrl: 'http://api.test/api/v1',
  supabaseUrl: 'http://supabase.test',
  supabaseAnonKey: 'public-anon-test-key',
);

/// A request seen by [FakeBackend].
class RecordedRequest {
  RecordedRequest(this.method, this.path, this.headers, this.body, this.query);

  final String method;
  final String path;
  final Map<String, dynamic> headers;
  final Object? body;
  final Map<String, dynamic> query;

  String? get authorization => headers['Authorization'] as String?;
}

/// A canned response.
class FakeResponse {
  const FakeResponse(this.status, [this.body]);

  final int status;
  final Object? body;
}

typedef FakeHandler = FutureOr<FakeResponse> Function(RecordedRequest request);

/// In-memory HTTP transport for the API [Dio]. Routes are `"METHOD /path"`
/// relative to `/api/v1` (e.g. `"GET /vessels/"`); unknown routes return the
/// server's 404 shape.
class FakeBackend implements HttpClientAdapter {
  final Map<String, FakeHandler> routes = {};
  final List<RecordedRequest> requests = [];

  void on(String route, FakeHandler handler) => routes[route] = handler;

  void json(String route, int status, Object? body) =>
      routes[route] = (_) => FakeResponse(status, body);

  List<RecordedRequest> calls(String route) {
    final parts = route.split(' ');
    return [
      for (final r in requests)
        if (r.method == parts[0] && r.path == parts[1]) r,
    ];
  }

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    var path = options.uri.path;
    const prefix = '/api/v1';
    if (path.startsWith(prefix)) path = path.substring(prefix.length);
    final request = RecordedRequest(
      options.method,
      path,
      Map<String, dynamic>.from(options.headers),
      options.data,
      Map<String, dynamic>.from(options.uri.queryParameters),
    );
    requests.add(request);
    final handler = routes['${options.method} $path'];
    final response = handler == null
        ? const FakeResponse(404, {'detail': 'Not Found', 'code': 'not_found'})
        : await handler(request);
    return ResponseBody.fromString(
      response.body == null ? '' : jsonEncode(response.body),
      response.status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// Scriptable stand-in for Supabase Auth.
class FakeAuthGateway implements AuthGateway {
  FakeAuthGateway({this.token, this.userId, this.email, this.fullNameHint});

  String? token;
  String? userId;
  String? email;
  String? fullNameHint;

  /// What [signUp] returns: a session (confirmation off) or not.
  bool signUpReturnsSession = true;

  /// Accounts that [signIn] accepts: email → (password, userId, token).
  final Map<String, (String, String, String)> accounts = {};

  /// Next token handed out by [refreshSession]; null makes refresh fail.
  String? refreshedToken;
  int refreshCalls = 0;
  int signOutCalls = 0;
  final List<String> resent = [];
  final _events = StreamController<AuthEvent>.broadcast(sync: true);

  void emit(AuthEvent event) => _events.add(event);

  void setSession({required String userId, required String token, String? email}) {
    this.userId = userId;
    this.token = token;
    this.email = email;
  }

  @override
  String? get currentAccessToken => token;

  @override
  String? get currentUserId => userId;

  @override
  String? get currentEmail => email;

  @override
  String? get currentFullNameHint => fullNameHint;

  @override
  Stream<AuthEvent> get events => _events.stream;

  @override
  Future<SignUpOutcome> signUp({
    required String email,
    required String password,
    required String fullName,
  }) async {
    fullNameHint = fullName;
    if (!signUpReturnsSession) return const SignUpOutcome(hasSession: false);
    final account = accounts[email];
    if (account == null) throw const AuthFailure('No test account configured');
    setSession(userId: account.$2, token: account.$3, email: email);
    emit(AuthEvent(AuthEventType.signedIn, userId: account.$2, email: email));
    return SignUpOutcome(hasSession: true, userId: account.$2);
  }

  @override
  Future<void> signIn({required String email, required String password}) async {
    final account = accounts[email];
    if (account == null || account.$1 != password) {
      throw const AuthFailure('Invalid login credentials', code: 'invalid_credentials');
    }
    setSession(userId: account.$2, token: account.$3, email: email);
    emit(AuthEvent(AuthEventType.signedIn, userId: account.$2, email: email));
  }

  @override
  Future<void> resendConfirmation(String email) async => resent.add(email);

  @override
  Future<String?> refreshSession() async {
    refreshCalls++;
    await Future<void>.delayed(Duration.zero);
    if (refreshedToken != null) token = refreshedToken;
    return refreshedToken;
  }

  @override
  Future<void> signOut() async {
    signOutCalls++;
    token = null;
    userId = null;
    email = null;
    emit(const AuthEvent(AuthEventType.signedOut));
  }
}

/// Provider overrides wiring the app to [gateway] and [backend].
List<Override> testOverrides({required FakeAuthGateway gateway, required FakeBackend backend}) => [
      appConfigProvider.overrideWithValue(testConfig),
      authGatewayProvider.overrideWithValue(gateway),
      httpClientAdapterProvider.overrideWithValue(backend),
    ];

/// A container for provider-level tests (no automatic retries).
ProviderContainer makeContainer({required FakeAuthGateway gateway, required FakeBackend backend}) {
  final container = ProviderContainer(
    overrides: testOverrides(gateway: gateway, backend: backend),
    retry: (_, _) => null,
  );
  return container;
}

/// A backend serving the captured fixtures for one signed-in user.
FakeBackend fixtureBackend() {
  final backend = FakeBackend();
  backend.json('POST /auth/provision', 200, fixture('provision_existing'));
  backend.json('GET /auth/me', 200, fixture('auth_me'));
  backend.json('GET /config/public', 200, fixture('config_public'));
  backend.json('GET /vessels/', 200, fixture('vessels_list'));
  backend.json('GET /cart/', 200, fixture('cart_empty'));
  backend.json('GET /products/', 200, fixture('products_list'));
  return backend;
}

/// Gateway with the fixture user's restored session.
FakeAuthGateway fixtureGateway() {
  final me = fixtureMap('auth_me');
  return FakeAuthGateway(
    token: 'token-a',
    userId: me['id'] as String,
    email: me['email'] as String,
  );
}

/// Polls until [condition] holds (real async I/O through Dio takes a few ticks).
Future<void> until(bool Function() condition, {Duration timeout = const Duration(seconds: 5)}) async {
  final deadline = DateTime.now().add(timeout);
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) throw StateError('Condition not met within $timeout');
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

/// Overrides for widget tests of screens that do not exercise auth or HTTP:
/// signed out, and every request answered with the server's 404 shape.
List<Override> baseTestOverrides() => testOverrides(gateway: FakeAuthGateway(), backend: FakeBackend());
