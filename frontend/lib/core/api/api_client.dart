import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

const String _baseUrl = 'http://localhost:8000/api/v1';

final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(BaseOptions(
    baseUrl: _baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 10),
    headers: {'Content-Type': 'application/json'},
  ));

  dio.interceptors.add(AuthInterceptor(ref));
  dio.interceptors.add(LogInterceptor(
    requestBody: true,
    responseBody: true,
    logPrint: (obj) {}, // Suppress in production
  ));

  return dio;
});

class AuthInterceptor extends Interceptor {
  final Ref _ref;
  static const _storage = FlutterSecureStorage();

  AuthInterceptor(this._ref);

  @override
  void onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final token = await _storage.read(key: 'access_token');
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      // Token expired — attempt refresh via Supabase
      final refreshToken = await _storage.read(key: 'refresh_token');
      if (refreshToken != null) {
        try {
          final supabase = Supabase.instance.client;
          final response = await supabase.auth.refreshSession();
          final session = response.session;

          if (session != null) {
            // Store the new tokens
            await _storage.write(
                key: 'access_token', value: session.accessToken);
            if (session.refreshToken != null) {
              await _storage.write(
                  key: 'refresh_token', value: session.refreshToken!);
            }

            // Retry the original request with the new token
            final options = err.requestOptions;
            options.headers['Authorization'] =
                'Bearer ${session.accessToken}';
            final retryResponse = await Dio().fetch(options);
            return handler.resolve(retryResponse);
          }
        } catch (_) {
          // Refresh failed — clear tokens and let the 401 propagate
          await _storage.delete(key: 'access_token');
          await _storage.delete(key: 'refresh_token');
        }
      }
    }
    handler.next(err);
  }
}
