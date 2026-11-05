import 'package:dio/dio.dart';
import 'package:helm_marine/core/api/api_error.dart';

/// Runs a request and parses its body; every failure surfaces as an
/// [ApiError] carrying the server's `{detail, code}`. Shared by the catalogue,
/// vessel-garage, checklist and notification-preference API clients.
Future<T> apiCall<T>(Future<Response<dynamic>> Function() send, T Function(dynamic data) parse) async {
  try {
    final response = await send();
    return parse(response.data);
  } on DioException catch (e) {
    throw ApiError.from(e)!;
  }
}

Map<String, dynamic> asMap(dynamic data) => (data as Map).cast<String, dynamic>();

List<Map<String, dynamic>> asList(dynamic data) =>
    [for (final e in data as List) (e as Map).cast<String, dynamic>()];
