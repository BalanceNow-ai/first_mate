/// Display-only formatting for the invoice's exact decimal strings.
///
/// Values arrive as strings such as `"237.50"`, `"-20.00"` or `"1200"` and are
/// never parsed into floating point: digits are grouped by string operations and
/// the decimal part is kept exactly as the server sent it. Arithmetic is done by
/// the server only.
library;

final _decimal = RegExp(r'^(-?)(\d+)(?:\.(\d+))?$');

/// Groups the integer part with commas (`"1234.5"` → `"1,234.5"`). Text that is
/// not a plain decimal is returned unchanged.
String groupDecimal(String value) {
  final m = _decimal.firstMatch(value.trim());
  if (m == null) return value;
  final sign = m.group(1)!;
  final whole = m.group(2)!;
  final frac = m.group(3);
  final buf = StringBuffer();
  for (var i = 0; i < whole.length; i++) {
    if (i > 0 && (whole.length - i) % 3 == 0) buf.write(',');
    buf.write(whole[i]);
  }
  return '$sign$buf${frac == null ? '' : '.$frac'}';
}

/// An amount in the invoice's stated currency, e.g. `NZD 237.50`. A missing
/// value reads "Not shown"; a missing currency is left out (never assumed NZD).
String formatInvoiceAmount(String? value, String? currency) {
  if (value == null) return 'Not shown';
  final grouped = groupDecimal(value);
  return currency == null || currency.isEmpty ? grouped : '$currency $grouped';
}

/// A quantity as printed (no currency); "Not shown" when missing.
String formatQuantity(String? value, [String? unit]) {
  if (value == null) return 'Not shown';
  final grouped = groupDecimal(value);
  return unit == null || unit.isEmpty ? grouped : '$grouped $unit';
}

/// True when the decimal string is exactly zero ("0", "0.00", "-0.00").
bool isZeroDecimal(String? value) {
  if (value == null) return false;
  final m = _decimal.firstMatch(value.trim());
  if (m == null) return false;
  return RegExp(r'^0+$').hasMatch(m.group(2)!) && RegExp(r'^0*$').hasMatch(m.group(3) ?? '');
}

/// Client-side shape check for an amount the owner types (the server validates
/// it again): up to 10 digits and 4 decimal places, optional leading minus.
final amountInputPattern = RegExp(r'^-?\d{1,10}(\.\d{1,4})?$');

/// Normalises typed amount text: trims, drops grouping commas and a leading
/// `$`. Returns null for empty text.
String? normaliseAmountInput(String text) {
  var t = text.trim().replaceAll(',', '');
  if (t.startsWith(r'$')) t = t.substring(1).trim();
  if (t.startsWith(r'-$')) t = '-${t.substring(2).trim()}';
  return t.isEmpty ? null : t;
}
