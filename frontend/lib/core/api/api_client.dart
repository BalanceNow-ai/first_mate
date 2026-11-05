import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/auth/auth_gateway.dart';
import 'package:helm_marine/core/config/app_config.dart';

/// Called when the session cannot be refreshed; the app signs the user out.
typedef SessionExpiredCallback = Future<void> Function();

/// Builds the API [Dio] for [baseUrl] with the auth interceptor installed.
Dio createApiDio({
  required String baseUrl,
  required AuthGateway gateway,
  required SessionExpiredCallback onSessionExpired,
  HttpClientAdapter? adapter,
}) {
  final dio = Dio(BaseOptions(
    baseUrl: baseUrl,
    connectTimeout: const Duration(seconds: 15),
    receiveTimeout: const Duration(seconds: 30),
    headers: {'Accept': 'application/json'},
    contentType: Headers.jsonContentType,
  ));
  if (adapter != null) dio.httpClientAdapter = adapter;
  dio.interceptors.add(AuthInterceptor(dio, gateway, onSessionExpired));
  return dio;
}

/// Transport override for tests (null = platform default).
final httpClientAdapterProvider = Provider<HttpClientAdapter?>((ref) => null);

/// The configured API client (base URL from [AppConfig]). A refresh failure
/// signs the user out through the auth controller.
final dioProvider = Provider<Dio>((ref) {
  final config = ref.watch(appConfigProvider);
  final gateway = ref.watch(authGatewayProvider);
  return createApiDio(
    baseUrl: config.apiBaseUrl,
    gateway: gateway,
    adapter: ref.watch(httpClientAdapterProvider),
    onSessionExpired: () => ref.read(authControllerProvider.notifier).sessionExpired(),
  );
});

/// Attaches the *current* Supabase access token to each request; on a 401 it
/// refreshes the session once (shared between concurrent requests) and retries
/// the request through the same configured [Dio]. When refreshing fails the
/// session is ended via [onSessionExpired].
class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._dio, this._gateway, this._onSessionExpired);

  static const retriedKey = 'helm_auth_retried';
  static const skipAuthKey = 'helm_skip_auth';

  final Dio _dio;
  final AuthGateway _gateway;
  final SessionExpiredCallback _onSessionExpired;
  Future<String?>? _refreshing;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    if (options.extra[skipAuthKey] != true) {
      final token = _gateway.currentAccessToken;
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      } else {
        options.headers.remove('Authorization');
      }
    }
    handler.next(options);
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    final request = err.requestOptions;
    final hadToken = request.headers['Authorization'] != null;
    if (err.response?.statusCode != 401 ||
        !hadToken ||
        request.extra[retriedKey] == true ||
        request.extra[skipAuthKey] == true) {
      return handler.next(_withApiError(err));
    }

    final token = await _refreshOnce();
    if (token == null) {
      await _onSessionExpired();
      return handler.next(_withApiError(err));
    }
    try {
      request.extra[retriedKey] = true;
      final response = await _dio.fetch<dynamic>(request);
      return handler.resolve(response);
    } on DioException catch (retryError) {
      if (retryError.response?.statusCode == 401) {
        await _onSessionExpired();
      }
      return handler.next(_withApiError(retryError));
    }
  }

  Future<String?> _refreshOnce() {
    final inflight = _refreshing;
    if (inflight != null) return inflight;
    final future = _gateway.refreshSession().whenComplete(() => _refreshing = null);
    _refreshing = future;
    return future;
  }

  /// Carries the parsed `{detail, code}` error on the exception.
  static DioException _withApiError(DioException err) {
    if (err.error is ApiError) return err;
    return err.copyWith(error: ApiError.fromDio(err));
  }
}
