import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:helm_marine/core/models/equipment.dart';

/// Parses a `YYYY-MM-DD` date typed by the user (null when empty or invalid).
DateTime? parseDay(String text) {
  final t = text.trim();
  final m = RegExp(r'^(\d{4})-(\d{1,2})-(\d{1,2})$').firstMatch(t);
  if (m == null) return null;
  final y = int.parse(m[1]!), mo = int.parse(m[2]!), d = int.parse(m[3]!);
  final date = DateTime(y, mo, d);
  return date.year == y && date.month == mo && date.day == d ? date : null;
}

/// Parses dollars typed by the user (`450`, `450.5`, `450.50`) into integer
/// cents without floating point. Null when empty; throws [FormatException]
/// when malformed.
int? parseDollarsToCents(String text) {
  final t = text.trim().replaceAll(',', '').replaceAll(r'$', '');
  if (t.isEmpty) return null;
  final m = RegExp(r'^(\d+)(?:\.(\d{1,2}))?$').firstMatch(t);
  if (m == null) throw const FormatException('Enter an amount like 450 or 450.50');
  final cents = (m[2] ?? '').padRight(2, '0');
  return int.parse(m[1]!) * 100 + int.parse(cents);
}

/// `45000` → `450.00` for an editable amount field.
String centsToDollarsText(int cents) => '${cents ~/ 100}.${(cents % 100).toString().padLeft(2, '0')}';

/// A date entered as `YYYY-MM-DD`, with a calendar button.
class DateField extends StatelessWidget {
  const DateField({
    super.key,
    required this.controller,
    required this.label,
    this.required = false,
    this.firstDate,
    this.lastDate,
  });

  final TextEditingController controller;
  final String label;
  final bool required;
  final DateTime? firstDate;
  final DateTime? lastDate;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      keyboardType: TextInputType.datetime,
      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9-]'))],
      decoration: InputDecoration(
        labelText: label,
        hintText: 'YYYY-MM-DD',
        suffixIcon: IconButton(
          icon: const Icon(Icons.calendar_today),
          tooltip: 'Choose $label',
          onPressed: () async {
            final now = DateTime.now();
            final picked = await showDatePicker(
              context: context,
              initialDate: parseDay(controller.text) ?? now,
              firstDate: firstDate ?? DateTime(1950),
              lastDate: lastDate ?? DateTime(now.year + 20),
            );
            if (picked != null) controller.text = dayString(picked);
          },
        ),
      ),
      validator: (v) {
        final t = v?.trim() ?? '';
        if (t.isEmpty) return required ? '$label is required' : null;
        return parseDay(t) == null ? 'Use the format YYYY-MM-DD' : null;
      },
    );
  }
}

/// An optional whole number within bounds.
FormFieldValidator<String> optionalInt(String label, int min, int max) => (v) {
      final t = v?.trim() ?? '';
      if (t.isEmpty) return null;
      final n = int.tryParse(t);
      if (n == null) return 'Enter a whole number';
      if (n < min || n > max) return '$label must be between $min and $max';
      return null;
    };

int? intOrNull(TextEditingController c) => int.tryParse(c.text.trim());

String? textOrNull(TextEditingController c) {
  final t = c.text.trim();
  return t.isEmpty ? null : t;
}

/// Standard dialog shell for the garage forms: scrollable, width-capped, with
/// Cancel / primary actions and an error line for server `detail`.
class FormDialog extends StatelessWidget {
  const FormDialog({
    super.key,
    required this.title,
    required this.formKey,
    required this.children,
    required this.onSubmit,
    required this.submitLabel,
    this.busy = false,
    this.error,
  });

  final String title;
  final GlobalKey<FormState> formKey;
  final List<Widget> children;
  final VoidCallback onSubmit;
  final String submitLabel;
  final bool busy;
  final String? error;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(title),
      scrollable: true,
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, minWidth: 280),
        child: Form(
          key: formKey,
          child: FocusTraversalGroup(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ),
                  ),
                for (final (i, c) in children.indexed) ...[
                  if (i > 0) const SizedBox(height: 12),
                  c,
                ],
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        ElevatedButton(
          onPressed: busy ? null : onSubmit,
          child: busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white, semanticsLabel: 'Saving'),
                )
              : Text(submitLabel),
        ),
      ],
    );
  }
}

/// Asks the user to confirm a destructive or significant action.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String message,
  required String confirmLabel,
  bool destructive = false,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        TextButton(
          onPressed: () => Navigator.pop(context, true),
          style: destructive ? TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error) : null,
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return ok == true;
}
