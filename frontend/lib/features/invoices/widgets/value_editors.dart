import 'package:flutter/material.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';

String? _amountValidator(String? text) {
  final v = normaliseAmountInput(text ?? '');
  if (v == null) return null;
  if (!amountInputPattern.hasMatch(v)) return 'Enter a number such as 237.50 (up to 4 decimal places)';
  return null;
}

String? _currencyValidator(String? text) {
  final v = (text ?? '').trim();
  if (v.isEmpty) return null;
  if (!RegExp(r'^[A-Za-z]{3}$').hasMatch(v)) return 'Use a three-letter code such as NZD, AUD or USD';
  return null;
}

/// Edits one header field. Returns `(value,)` — `(null,)` records "not on
/// the invoice" — or null when cancelled.
Future<(String?,)?> showFieldEditor(BuildContext context, InvoiceField field) {
  return showDialog<(String?,)>(context: context, builder: (context) => _FieldEditor(field: field));
}

class _FieldEditor extends StatefulWidget {
  const _FieldEditor({required this.field});

  final InvoiceField field;

  @override
  State<_FieldEditor> createState() => _FieldEditorState();
}

class _FieldEditorState extends State<_FieldEditor> {
  final _form = GlobalKey<FormState>();
  late final _text = TextEditingController(text: widget.field.value ?? '');
  bool _notOnInvoice = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  void _save() {
    if (!_form.currentState!.validate()) return;
    if (_notOnInvoice) return Navigator.pop(context, (null,));
    final f = widget.field;
    String? value;
    if (f.isAmount) {
      value = normaliseAmountInput(_text.text);
    } else if (f.name == 'currency') {
      final t = _text.text.trim().toUpperCase();
      value = t.isEmpty ? null : t;
    } else {
      final t = _text.text.trim();
      value = t.isEmpty ? null : t;
    }
    Navigator.pop(context, (value,));
  }

  @override
  Widget build(BuildContext context) {
    final f = widget.field;
    return AlertDialog(
      title: Text('Edit ${f.label.toLowerCase()}'),
      content: Form(
        key: _form,
        child: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (f.extractedValue != null) Text('Read from the document as: ${f.extractedValue}'),
              const SizedBox(height: 12),
              TextFormField(
                controller: _text,
                enabled: !_notOnInvoice,
                autofocus: true,
                maxLines: f.name == 'warranty' || f.name == 'follow_up' ? 3 : 1,
                keyboardType: f.isAmount ? const TextInputType.numberWithOptions(decimal: true, signed: true) : null,
                textCapitalization: f.name == 'currency' ? TextCapitalization.characters : TextCapitalization.none,
                decoration: InputDecoration(
                  labelText: f.label,
                  helperText: f.isAmount
                      ? 'As printed, without the currency symbol'
                      : f.name == 'currency'
                          ? 'The currency printed on the invoice'
                          : null,
                ),
                validator: f.isAmount
                    ? _amountValidator
                    : f.name == 'currency'
                        ? _currencyValidator
                        : null,
                onFieldSubmitted: (_) => _save(),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _notOnInvoice,
                onChanged: (v) => setState(() => _notOnInvoice = v ?? false),
                title: const Text('This is not on the invoice'),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: const Text('Save')),
      ],
    );
  }
}

/// Edits (or, with no [line], adds) an invoice line. Returns only the values
/// that changed (empty text = "not shown"), or null when cancelled.
Future<Map<String, String?>?> showLineEditor(BuildContext context, {InvoiceLine? line}) {
  return showDialog<Map<String, String?>>(context: context, builder: (context) => _LineEditor(line: line));
}

class _LineEditor extends StatefulWidget {
  const _LineEditor({this.line});

  final InvoiceLine? line;

  @override
  State<_LineEditor> createState() => _LineEditorState();
}

class _LineEditorState extends State<_LineEditor> {
  static const _textColumns = ['description', 'part_number', 'quantity', 'unit', 'unit_price', 'line_total', 'tax_printed'];
  static const _amountColumns = {'quantity', 'unit_price', 'line_total', 'tax_printed'};

  final _form = GlobalKey<FormState>();
  late String _kind = widget.line?.kind ?? 'unknown';
  late final Map<String, TextEditingController> _controllers = {
    for (final c in _textColumns) c: TextEditingController(text: widget.line?.valueOf(c) ?? ''),
  };

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  String? _valueFor(String column) {
    final text = _controllers[column]!.text;
    if (_amountColumns.contains(column)) return normaliseAmountInput(text);
    final t = text.trim();
    return t.isEmpty ? null : t;
  }

  void _save() {
    if (!_form.currentState!.validate()) return;
    final line = widget.line;
    final out = <String, String?>{};
    if (line == null || _kind != line.kind) out['kind'] = _kind;
    for (final c in _textColumns) {
      final v = _valueFor(c);
      if (line == null) {
        if (v != null) out[c] = v;
      } else if (v != line.valueOf(c)) {
        out[c] = v;
      }
    }
    Navigator.pop(context, out);
  }

  @override
  Widget build(BuildContext context) {
    final line = widget.line;
    Widget field(String column, {bool amount = false}) {
      final was = line?.extractedValues?[column];
      final changed = line != null && line.correctedFields.contains(column);
      return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextFormField(
          controller: _controllers[column],
          keyboardType: amount ? const TextInputType.numberWithOptions(decimal: true, signed: true) : null,
          decoration: InputDecoration(
            labelText: lineValueLabels[column],
            helperText: changed ? 'Read from the document as: ${was ?? 'not shown'}' : null,
          ),
          validator: amount ? _amountValidator : null,
        ),
      );
    }

    return AlertDialog(
      title: Text(line == null ? 'Add a line' : 'Edit line ${line.lineNumber}'),
      content: Form(
        key: _form,
        child: SizedBox(
          width: 460,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: DropdownButtonFormField<String>(
                  isExpanded: true,
                    initialValue: _kind,
                    decoration: const InputDecoration(labelText: 'Type'),
                    items: [
                      for (final e in lineKindLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: (v) => setState(() => _kind = v ?? 'unknown'),
                  ),
                ),
                field('description'),
                field('part_number'),
                field('quantity', amount: true),
                field('unit'),
                field('unit_price', amount: true),
                field('line_total', amount: true),
                field('tax_printed', amount: true),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: Text(line == null ? 'Add line' : 'Save line')),
      ],
    );
  }
}

/// Edits a question's text (a draft or a new question). Null when cancelled.
Future<String?> showQuestionEditor(BuildContext context, {required String title, String initial = ''}) {
  return showDialog<String>(context: context, builder: (context) => _QuestionEditor(title: title, initial: initial));
}

class _QuestionEditor extends StatefulWidget {
  const _QuestionEditor({required this.title, required this.initial});

  final String title;
  final String initial;

  @override
  State<_QuestionEditor> createState() => _QuestionEditorState();
}

class _QuestionEditorState extends State<_QuestionEditor> {
  final _form = GlobalKey<FormState>();
  late final _text = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: Form(
        key: _form,
        child: SizedBox(
          width: 480,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Keep it factual. This is saved as a private draft; nothing is sent until you choose to.'),
              const SizedBox(height: 12),
              TextFormField(
                controller: _text,
                autofocus: true,
                minLines: 3,
                maxLines: 8,
                maxLength: 2000,
                decoration: const InputDecoration(labelText: 'Question'),
                validator: (v) => (v ?? '').trim().isEmpty ? 'Write a question' : null,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (_form.currentState!.validate()) Navigator.pop(context, _text.text.trim());
          },
          child: const Text('Save draft'),
        ),
      ],
    );
  }
}
