import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';
import 'package:helm_marine/features/invoices/providers/invoice_providers.dart';
import 'package:helm_marine/features/invoices/widgets/document_viewer.dart';
import 'package:helm_marine/features/invoices/widgets/explanation_view.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';
import 'package:helm_marine/features/invoices/widgets/value_editors.dart';

/// Width at which the document and the values sit side by side.
const reviewSideBySideBreakpoint = 900.0;

/// `/invoices/:id/review` — the document next to the editable fields and lines:
/// what was read vs. what you corrected, reading certainty and "needs your
/// confirmation", with the server's exact sums after every change.
class InvoiceReviewScreen extends ConsumerStatefulWidget {
  const InvoiceReviewScreen({super.key, required this.invoiceId, this.initialSelection});

  final String invoiceId;
  final String? initialSelection;

  @override
  ConsumerState<InvoiceReviewScreen> createState() => _InvoiceReviewScreenState();
}

class _InvoiceReviewScreenState extends ConsumerState<InvoiceReviewScreen> {
  late String? _selected = widget.initialSelection;
  bool _busy = false;
  bool _recalculating = false;

  /// This screen's own messenger, so confirmations appear in its Scaffold above the
  /// review bar instead of in the app shell's Scaffold on top of it.
  final _messengerKey = GlobalKey<ScaffoldMessengerState>();

  ScaffoldMessengerState? get _messenger => _messengerKey.currentState;

  InvoiceController get _controller => ref.read(invoiceControllerProvider(widget.invoiceId).notifier);

  void _snack(String text) {
    if (mounted) _messenger?.showSnackBar(SnackBar(content: Text(text), behavior: SnackBarBehavior.floating));
  }

  /// Applies a correction, then asks the server to recalculate the sums.
  Future<void> _mutate(
    Future<InvoiceDetail> Function(InvoicesApi api, InvoiceDetail current) op, {
    String? done,
    bool recalculate = true,
  }) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await _controller.apply(op);
      if (done != null) _snack(done);
      if (recalculate) await _recalculate();
    } catch (e) {
      if (mounted) await showMutationError(context, e, onReload: () => _controller.reload(), messenger: _messenger);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _recalculate() async {
    if (!mounted) return;
    setState(() => _recalculating = true);
    try {
      await _controller.explain();
    } catch (_) {
      // The sums panel offers a manual retry.
    } finally {
      if (mounted) setState(() => _recalculating = false);
    }
  }

  Future<void> _editField(InvoiceField field) async {
    setState(() => _selected = 'field:${field.name}');
    final result = await showFieldEditor(context, field);
    if (result == null) return;
    await _mutate(
      (api, cur) => api.correctFields(cur.id, expectedVersion: cur.revision.version, changes: {field.name: result.$1}),
      done: '${field.label} saved.',
    );
  }

  Future<void> _confirmField(InvoiceField field) => _mutate(
    (api, cur) => api.correctFields(cur.id, expectedVersion: cur.revision.version, changes: {field.name: field.value}),
    done: '${field.label} confirmed as printed.',
  );

  Future<void> _editLine(InvoiceLine line) async {
    setState(() => _selected = line.confirmKey);
    final changes = await showLineEditor(context, line: line);
    if (changes == null) return;
    await _mutate(
      (api, cur) => api.correctLine(cur.id, line.id, expectedVersion: line.version, changes: changes),
      done: changes.isEmpty ? 'Line ${line.lineNumber} confirmed as printed.' : 'Line ${line.lineNumber} saved.',
    );
  }

  Future<void> _confirmLine(InvoiceLine line) => _mutate(
    (api, cur) => api.correctLine(cur.id, line.id, expectedVersion: line.version),
    done: 'Line ${line.lineNumber} confirmed as printed.',
  );

  Future<void> _removeLine(InvoiceLine line) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove line ${line.lineNumber}?'),
        content: const Text(
          'Use this for something that was misread as a line (for example a note). What was read from the '
          'document is kept on record.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove line')),
        ],
      ),
    );
    if (ok != true) return;
    await _mutate(
      (api, cur) => api.deleteLine(cur.id, line.id, expectedVersion: line.version),
      done: 'Line ${line.lineNumber} removed.',
    );
  }

  Future<void> _addLine() async {
    final values = await showLineEditor(context);
    if (values == null || values.isEmpty) return;
    await _mutate(
      (api, cur) => api.addLine(cur.id, expectedVersion: cur.revision.version, values: values),
      done: 'Line added.',
    );
  }

  Future<void> _markReviewed() => _mutate(
    (api, cur) => api.review(cur.id, expectedVersion: cur.revision.version),
    done: 'Marked as reviewed. The checks and comparisons are no longer provisional.',
  );

  @override
  Widget build(BuildContext context) {
    final invoice = ref.watch(invoiceControllerProvider(widget.invoiceId));
    final current = invoice.value;
    return ScaffoldMessenger(
      key: _messengerKey,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Check the details'),
          leading: BackButton(onPressed: () => context.go('/invoices/${widget.invoiceId}')),
        ),
        bottomNavigationBar: current == null || !current.provisional
            ? null
            : _ReviewBar(invoice: current, busy: _busy, onMarkReviewed: _markReviewed),
        body: invoice.when(
          skipLoadingOnRefresh: true,
          skipLoadingOnReload: true,
          loading: () => const LoadingView(message: 'Loading the invoice…'),
          error: (e, _) => ErrorView(
            error: e,
            title: ApiError.from(e)?.isNotFound == true ? 'Invoice not found' : 'Could not load the invoice',
            onRetry: ApiError.from(e)?.isNotFound == true
                ? null
                : () => ref.invalidate(invoiceControllerProvider(widget.invoiceId)),
          ),
          data: (inv) => LayoutBuilder(
            builder: (context, box) {
              final wide = box.maxWidth >= reviewSideBySideBreakpoint;
              final assetId = inv.revision.brief.sourceAssetId;
              final highlights = _highlights(inv);
              final document = assetId == null
                  ? const Card(
                      child: ListTile(
                        leading: Icon(Icons.keyboard_outlined),
                        title: Text('No document'),
                        subtitle: Text('This revision was entered by hand.'),
                      ),
                    )
                  : InvoiceDocumentViewer(
                      assetId: assetId,
                      highlights: highlights,
                      selectedKey: _selected,
                      onSelect: (key) => setState(() => _selected = key),
                    );
              final editor = _Editor(
                invoice: inv,
                selectedKey: _selected,
                busy: _busy,
                recalculating: _recalculating,
                hasDocument: assetId != null,
                onSelect: (key) => setState(() => _selected = key),
                onEditField: _editField,
                onConfirmField: _confirmField,
                onEditLine: _editLine,
                onConfirmLine: _confirmLine,
                onRemoveLine: _removeLine,
                onAddLine: _addLine,
                onRecalculate: _recalculate,
                onMarkReviewed: _markReviewed,
              );
              if (wide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      flex: 5,
                      child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: document),
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(flex: 6, child: editor),
                  ],
                );
              }
              return editor.withLeading(document);
            },
          ),
        ),
      ),
    );
  }

  static List<DocumentHighlight> _highlights(InvoiceDetail inv) => [
    for (final f in inv.revision.orderedFields)
      if (f.region != null) DocumentHighlight(key: 'field:${f.name}', label: f.label, page: f.page, region: f.region!),
    for (final l in inv.lines)
      if (l.region != null)
        DocumentHighlight(
          key: l.confirmKey,
          label: 'Line ${l.lineNumber}${l.description == null ? '' : ' (${l.description})'}',
          page: l.page,
          region: l.region!,
        ),
  ];
}

class _Editor extends StatelessWidget {
  const _Editor({
    required this.invoice,
    required this.selectedKey,
    required this.busy,
    required this.recalculating,
    required this.hasDocument,
    required this.onSelect,
    required this.onEditField,
    required this.onConfirmField,
    required this.onEditLine,
    required this.onConfirmLine,
    required this.onRemoveLine,
    required this.onAddLine,
    required this.onRecalculate,
    required this.onMarkReviewed,
    this.leading,
  });

  /// Shown above the values on narrow layouts (the document).
  final Widget? leading;

  _Editor withLeading(Widget leading) => _Editor(
    invoice: invoice,
    selectedKey: selectedKey,
    busy: busy,
    recalculating: recalculating,
    hasDocument: hasDocument,
    onSelect: onSelect,
    onEditField: onEditField,
    onConfirmField: onConfirmField,
    onEditLine: onEditLine,
    onConfirmLine: onConfirmLine,
    onRemoveLine: onRemoveLine,
    onAddLine: onAddLine,
    onRecalculate: onRecalculate,
    onMarkReviewed: onMarkReviewed,
    leading: leading,
  );

  final InvoiceDetail invoice;
  final String? selectedKey;
  final bool busy;
  final bool recalculating;
  final bool hasDocument;
  final ValueChanged<String> onSelect;
  final ValueChanged<InvoiceField> onEditField;
  final ValueChanged<InvoiceField> onConfirmField;
  final ValueChanged<InvoiceLine> onEditLine;
  final ValueChanged<InvoiceLine> onConfirmLine;
  final ValueChanged<InvoiceLine> onRemoveLine;
  final VoidCallback onAddLine;
  final VoidCallback onRecalculate;
  final VoidCallback onMarkReviewed;

  @override
  Widget build(BuildContext context) {
    final inv = invoice;
    final currency = inv.revision.currency;
    final exp = inv.explanation;
    final current = exp != null && !exp.stale && exp.revisionId == inv.revision.id ? exp : null;
    final checks = {for (final l in current?.content.lines ?? const <ExplainedLine>[]) l.lineId: l.arithmetic};
    final unparsed = [
      for (final u in inv.revision.unparsedText)
        // Bank/card details are masked by the server; we don't show those rows at all.
        if (u.text != null && !u.text!.contains('[masked]')) u,
    ];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ?leading,
        if (inv.provisional)
          const Text(
            'Compare each value with the document. Values marked “Needs your confirmation” were hard to read: '
            'correct them, or confirm them as printed.',
          )
        else
          Card(
            child: ListTile(
              leading: const Icon(Icons.task_alt, color: HelmTheme.success),
              title: const Text('Reviewed'),
              subtitle: Text(
                'You reviewed these details'
                '${inv.revision.reviewedAt == null ? '' : ' on ${inv.revision.reviewedAt!.substring(0, 10)}'}.',
              ),
            ),
          ),
        const SectionHeading('Invoice details'),
        for (final f in inv.revision.orderedFields)
          _FieldTile(
            field: f,
            currency: currency,
            selected: selectedKey == 'field:${f.name}',
            busy: busy,
            onSelect: f.region == null ? null : () => onSelect('field:${f.name}'),
            onEdit: () => onEditField(f),
            onConfirm: () => onConfirmField(f),
          ),
        const SectionHeading('Lines'),
        if (inv.lines.isEmpty)
          const Card(child: ListTile(title: Text('No lines yet. Add each charge from the invoice.'))),
        for (final l in inv.lines)
          _LineTile(
            line: l,
            currency: l.currency ?? currency,
            check: checks[l.id],
            selected: selectedKey == l.confirmKey,
            busy: busy,
            onSelect: l.region == null ? null : () => onSelect(l.confirmKey),
            onEdit: () => onEditLine(l),
            onConfirm: () => onConfirmLine(l),
            onRemove: () => onRemoveLine(l),
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: busy ? null : onAddLine,
            icon: const Icon(Icons.add),
            label: const Text('Add a line'),
          ),
        ),
        if (unparsed.isNotEmpty) ...[
          const SectionHeading(
            'Other text on the document',
            subtitle: 'Read but not placed in a field or line. Rows with bank or card details are not shown.',
          ),
          for (final u in unparsed)
            ListTile(
              dense: true,
              leading: const Icon(Icons.notes),
              title: Text(u.text!),
              subtitle: u.page == null ? null : Text('Page ${u.page}'),
            ),
        ],
        const SectionHeading('Sums', subtitle: 'Recalculated exactly by Helm from the values above'),
        if (recalculating)
          const Card(
            child: ListTile(leading: CircularProgressIndicator(), title: Text('Recalculating…')),
          )
        else if (current != null)
          TotalsPanel(checks: current.content.arithmetic)
        else
          Card(
            child: ListTile(
              leading: const Icon(Icons.calculate_outlined),
              title: const Text('The sums haven’t been checked for the latest values'),
              trailing: TextButton(onPressed: busy ? null : onRecalculate, child: const Text('Check the sums')),
            ),
          ),
        const SizedBox(height: 16),
        const SizedBox(height: 24),
      ],
    );
  }
}

/// Always-visible review action: what still needs confirming, and the explicit
/// "Mark as reviewed" (comparisons stay provisional until then).
class _ReviewBar extends StatelessWidget {
  const _ReviewBar({required this.invoice, required this.busy, required this.onMarkReviewed});

  final InvoiceDetail invoice;
  final bool busy;
  final VoidCallback onMarkReviewed;

  @override
  Widget build(BuildContext context) {
    final pending = invoice.needsConfirmation.length;
    final empty = invoice.lines.isEmpty && invoice.revision.fields['total']?.value == null;
    return Material(
      elevation: 8,
      color: Theme.of(context).colorScheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: Row(
            children: [
              Expanded(
                child: Semantics(
                  liveRegion: true,
                  child: Text(
                    pending > 0
                        ? '$pending ${pending == 1 ? 'value still needs' : 'values still need'} your confirmation '
                              'before you can mark the invoice reviewed.'
                        : empty
                        ? 'Add the lines or the total first.'
                        : 'Checked everything against the document?',
                    style: TextStyle(
                      color: pending > 0 ? HelmTheme.warning : null,
                      fontWeight: pending > 0 ? FontWeight.w600 : null,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                height: 52,
                child: FilledButton.icon(
                  onPressed: busy || pending > 0 || empty ? null : onMarkReviewed,
                  icon: const Icon(Icons.task_alt),
                  label: const Text('Mark as reviewed'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FieldTile extends StatelessWidget {
  const _FieldTile({
    required this.field,
    required this.currency,
    required this.selected,
    required this.busy,
    required this.onSelect,
    required this.onEdit,
    required this.onConfirm,
  });

  final InvoiceField field;
  final String? currency;
  final bool selected;
  final bool busy;
  final VoidCallback? onSelect;
  final VoidCallback onEdit;
  final VoidCallback onConfirm;

  String _show(String? v) {
    if (v == null) return 'Not shown';
    return field.isAmount ? formatInvoiceAmount(v, currency) : v;
  }

  @override
  Widget build(BuildContext context) {
    final f = field;
    return Card(
      shape: selected
          ? RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: HelmTheme.coral, width: 2),
            )
          : null,
      child: InkWell(
        onTap: onSelect,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: MergeSemantics(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(f.label, style: Theme.of(context).textTheme.labelMedium),
                          Text(
                            f.illegible ? 'Printed but hard to read' : _show(f.value),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                        ],
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Edit ${f.label.toLowerCase()}',
                    onPressed: busy ? null : onEdit,
                    icon: const Icon(Icons.edit_outlined),
                  ),
                ],
              ),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  SourceBadge(f.displaySource),
                  if (f.displaySource == ValueSource.extracted) CertaintyChip(f.certainty),
                  if (f.needsConfirmation) const NeedsConfirmationChip(),
                ],
              ),
              if (f.differsFromExtracted)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    'Read from the document as: ${_show(f.extractedValue)}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              if (f.page != null)
                Text(
                  'Source: ${f.region?.describe(f.page) ?? 'page ${f.page}'}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              if (f.needsConfirmation)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: busy ? null : onConfirm,
                    icon: const Icon(Icons.check),
                    label: Text('Confirm ${f.label.toLowerCase()} as printed'),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LineTile extends StatelessWidget {
  const _LineTile({
    required this.line,
    required this.currency,
    required this.check,
    required this.selected,
    required this.busy,
    required this.onSelect,
    required this.onEdit,
    required this.onConfirm,
    required this.onRemove,
  });

  final InvoiceLine line;
  final String? currency;
  final LineCheck? check;
  final bool selected;
  final bool busy;
  final VoidCallback? onSelect;
  final VoidCallback onEdit;
  final VoidCallback onConfirm;
  final VoidCallback onRemove;

  static const _amountColumns = {'unit_price', 'line_total', 'tax_printed'};

  String _show(String column, String? v) {
    if (column == 'kind') return lineKindLabels[v] ?? (v ?? 'Not shown');
    if (v == null) return 'Not shown';
    if (_amountColumns.contains(column)) return formatInvoiceAmount(v, currency);
    if (column == 'quantity') return groupDecimal(v);
    return v;
  }

  @override
  Widget build(BuildContext context) {
    final l = line;
    final values = [
      ('quantity', l.quantity),
      ('unit', l.unit),
      ('unit_price', l.unitPrice),
      ('line_total', l.lineTotal),
      if (l.taxPrinted != null) ('tax_printed', l.taxPrinted),
      if (l.partNumber != null) ('part_number', l.partNumber),
    ];
    return Card(
      shape: selected
          ? RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: HelmTheme.coral, width: 2),
            )
          : null,
      child: InkWell(
        onTap: onSelect,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: MergeSemantics(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Line ${l.lineNumber} · ${l.kindLabel}', style: Theme.of(context).textTheme.labelMedium),
                          Text(l.description ?? 'No description', style: Theme.of(context).textTheme.titleMedium),
                        ],
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Edit line ${l.lineNumber}',
                    onPressed: busy ? null : onEdit,
                    icon: const Icon(Icons.edit_outlined),
                  ),
                  IconButton(
                    tooltip: 'Remove line ${l.lineNumber}',
                    onPressed: busy ? null : onRemove,
                    icon: const Icon(Icons.delete_outline),
                  ),
                ],
              ),
              Wrap(
                spacing: 16,
                runSpacing: 4,
                children: [
                  for (final (column, value) in values)
                    MergeSemantics(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(lineValueLabels[column]!, style: Theme.of(context).textTheme.labelSmall),
                          Text(l.illegible.contains(column) ? 'Hard to read' : _show(column, value)),
                          if (l.correctedFields.contains(column))
                            Text(
                              'Read as: ${_show(column, l.extractedValues?[column])}',
                              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText),
                            ),
                        ],
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  SourceBadge(l.source),
                  if (l.source == ValueSource.extracted) CertaintyChip(l.certainty),
                  if (l.needsConfirmation) const NeedsConfirmationChip(),
                ],
              ),
              if (l.page != null)
                Text(
                  'Source: ${l.region?.describe(l.page) ?? 'page ${l.page}'}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              if (check != null) ...[
                const SizedBox(height: 6),
                LineCheckSummary(check: check!, currency: currency, quantity: l.quantity, unitPrice: l.unitPrice),
              ],
              if (l.needsConfirmation)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: busy ? null : onConfirm,
                    icon: const Icon(Icons.check),
                    label: Text('Confirm line ${l.lineNumber} as printed'),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
