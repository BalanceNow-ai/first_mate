import 'package:dio/dio.dart';

/// One entry of a validation error (`errors` on a 422 response).
class FieldError {
  const FieldError({required this.loc, required this.msg, required this.type});

  final List<String> loc;
  final String msg;
  final String type;

  /// The field name (last location segment), e.g. `nickname`.
  String get field => loc.isEmpty ? '' : loc.last;

  factory FieldError.fromJson(Map<String, dynamic> json) => FieldError(
        loc: [for (final p in (json['loc'] as List? ?? const [])) '$p'],
        msg: json['msg'] as String? ?? '',
        type: json['type'] as String? ?? '',
      );
}

/// An API failure following the server contract `{detail, code, ...}`.
class ApiError implements Exception {
  const ApiError({
    required this.statusCode,
    required this.code,
    required this.detail,
    this.errors = const [],
    this.extra = const {},
  });

  /// HTTP status, or `null` when no response was received.
  final int? statusCode;

  /// Machine-readable code, e.g. `profile_not_provisioned`, `insufficient_stock`.
  final String code;

  /// Human-readable message from the server (safe to show).
  final String detail;

  /// Field errors for `validation_error`.
  final List<FieldError> errors;

  /// Any additional fields the server returned (e.g. `available_quantity`).
  final Map<String, dynamic> extra;

  static const networkCode = 'network_error';

  bool get isNetwork => code == networkCode;
  bool get isUnauthorized => statusCode == 401;
  bool get isProfileNotProvisioned => code == 'profile_not_provisioned';
  bool get isNotFound => statusCode == 404;

  /// Parses an error body. Unknown shapes fall back to a generic message rather
  /// than echoing raw response text.
  factory ApiError.fromResponse(int? statusCode, Object? body) {
    if (body is Map) {
      final map = body.cast<String, dynamic>();
      final detail = map['detail'];
      return ApiError(
        statusCode: statusCode,
        code: map['code'] as String? ?? _codeFor(statusCode),
        detail: detail is String && detail.isNotEmpty
            ? detail
            : _messageFor(statusCode),
        errors: [
          for (final e in (map['errors'] as List? ?? const []))
            if (e is Map) FieldError.fromJson(e.cast<String, dynamic>()),
        ],
        extra: {
          for (final entry in map.entries)
            if (!const {'detail', 'code', 'errors'}.contains(entry.key))
              entry.key: entry.value,
        },
      );
    }
    return ApiError(
      statusCode: statusCode,
      code: _codeFor(statusCode),
      detail: _messageFor(statusCode),
    );
  }

  factory ApiError.fromDio(DioException e) {
    final response = e.response;
    if (response == null) {
      return const ApiError(
        statusCode: null,
        code: networkCode,
        detail: 'Could not reach Helm. Check your connection and try again.',
      );
    }
    return ApiError.fromResponse(response.statusCode, response.data);
  }

  /// Converts any thrown object into an [ApiError] where possible.
  static ApiError? from(Object error) {
    if (error is ApiError) return error;
    if (error is DioException) {
      final inner = error.error;
      if (inner is ApiError) return inner;
      return ApiError.fromDio(error);
    }
    return null;
  }

  static String _codeFor(int? status) => switch (status) {
        401 => 'invalid_token',
        403 => 'forbidden',
        404 => 'not_found',
        422 => 'validation_error',
        _ => 'http_error',
      };

  static String _messageFor(int? status) => switch (status) {
        401 => 'Your session has expired. Please sign in again.',
        403 => 'You do not have permission to do that.',
        404 => 'Not found.',
        _ when status != null && status >= 500 =>
          'Helm is having trouble right now. Please try again shortly.',
        _ => 'Something went wrong. Please try again.',
      };

  @override
  String toString() => detail;
}

/// A user-presentable message for any error (never raw exception internals).
String describeError(Object error) {
  final api = ApiError.from(error);
  if (api != null) {
    if (api.errors.isNotEmpty) {
      final first = api.errors.first;
      return first.field.isEmpty
          ? api.detail
          : '${api.detail}: ${first.field} — ${first.msg}';
    }
    return api.detail;
  }
  final text = error.toString();
  // Auth/other exceptions with a message (e.g. AuthFailure) render directly.
  if (text.startsWith('Exception: ')) return text.substring(11);
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}
