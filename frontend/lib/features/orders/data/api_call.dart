import 'package:dio/dio.dart';
import 'package:helm_marine/core/api/api_error.dart';

/// Sends [send] and parses the body; every failure becomes an [ApiError]
/// carrying the server's `{detail, code}` (and any extra fields).
Future<T> apiCall<T>(Future<Response<dynamic>> Function() send, T Function(dynamic data) parse) async {
  try {
    final response = await send();
    return parse(response.data);
  } on DioException catch (e) {
    throw ApiError.from(e)!;
  }
}

Map<String, dynamic> asMap(dynamic data) => (data as Map).cast<String, dynamic>();

List<Map<String, dynamic>> asMapList(dynamic data) =>
    [for (final e in data as List) (e as Map).cast<String, dynamic>()];
