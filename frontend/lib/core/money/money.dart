import 'package:intl/intl.dart';

final _grouping = NumberFormat.decimalPattern('en_NZ');

/// Formats integer minor units (cents) for display, e.g. `7490` → `$74.90`.
///
/// All money in the app is carried as integer cents exactly as the server sends
/// it (`*_cents`); the server computes every price and total. This is the only
/// place cents become text, and it never goes through floating point: dollars
/// and cents are split with integer arithmetic and grouped with `intl` (en_NZ).
String formatCents(int cents, {String currency = 'NZD', bool showCode = false}) {
  final negative = cents < 0;
  final abs = cents.abs();
  final dollars = _grouping.format(abs ~/ 100);
  final minor = (abs % 100).toString().padLeft(2, '0');
  final symbol = currency == 'NZD' ? r'$' : '$currency ';
  final text = '${negative ? '-' : ''}$symbol$dollars.$minor';
  return showCode && currency == 'NZD' ? '$text NZD' : text;
}

/// Reads a required integer cents field (rejects floats and strings).
int centsFrom(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value is int) return value;
  throw FormatException('Expected integer cents in "$key", got $value');
}

/// Reads an optional integer cents field.
int? optionalCentsFrom(Map<String, dynamic> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is int) return value;
  throw FormatException('Expected integer cents in "$key", got $value');
}
