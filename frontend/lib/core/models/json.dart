/// Small strict readers for API JSON. A missing or wrongly-typed required field
/// throws a [FormatException] naming the field, so contract drift fails loudly
/// in tests instead of silently rendering defaults.
library;

T req<T>(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is T) return value;
  throw FormatException('Field "$key": expected $T, got ${value.runtimeType}');
}

T? opt<T>(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is T) return value;
  throw FormatException('Field "$key": expected $T?, got ${value.runtimeType}');
}

double? optDouble(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is num) return value.toDouble();
  throw FormatException('Field "$key": expected number, got ${value.runtimeType}');
}

DateTime reqDate(Map<String, dynamic> json, String key) =>
    DateTime.parse(req<String>(json, key));

List<String> stringList(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return const [];
  if (value is List) return [for (final v in value) v as String];
  throw FormatException('Field "$key": expected list, got ${value.runtimeType}');
}

Map<String, dynamic>? optMap(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is Map) return value.cast<String, dynamic>();
  throw FormatException('Field "$key": expected object, got ${value.runtimeType}');
}

Map<String, dynamic> reqMap(Map<String, dynamic> json, String key) {
  final value = optMap(json, key);
  if (value == null) throw FormatException('Field "$key": missing object');
  return value;
}

List<Map<String, dynamic>> mapList(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is List) {
    return [for (final v in value) (v as Map).cast<String, dynamic>()];
  }
  throw FormatException('Field "$key": expected list, got ${value.runtimeType}');
}
