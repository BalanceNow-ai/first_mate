import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';

String _checkStatusLabel(String status) => switch (status) {
      'matches' => 'Adds up',
      'differs' => 'Does not add up',
      'printed_only' => 'Only the amount is printed',
      'computed_only' => 'No amount printed — calculated',
      'not_printed' => 'Not printed',
      _ => 'Cannot be checked',
    };

String _reasonText(String reason) => switch (reason) {
      'currency_unknown' => 'the currency is not known',
      'mixed_currency' => 'amounts are in more than one currency',
      'currency_unrecognised' => 'the currency is not recognised',
      'illegible_values' => 'some values are hard to read',
      'missing_quantity' => 'no quantity is shown',
      'missing_unit_price' => 'no unit price is shown',
      'missing_line_total' => 'no line amount is shown',
      'line_amount_unknown' => 'a line amount is unknown',
      'subtotal_not_printed' => 'no subtotal is printed',
      'total_not_printed' => 'no total is printed',
      'subtotal_illegible' => 'the subtotal is hard to read',
      'total_illegible' => 'the total is hard to read',
      'subtotal_inputs_unknown' || 'total_inputs_unknown' => 'the values needed are unknown',
      'tax_not_stated' => 'the tax is not stated, so the difference may be tax',
      _ => reason.replaceAll('_', ' '),
    };

Color _statusColor(String status) => switch (status) {
      'matches' => HelmTheme.success,
      'differs' => HelmTheme.warning,
      _ => HelmTheme.mutedText,
    };

IconData _statusIcon(String status) => switch (status) {
      'matches' => Icons.check_circle_outline,
      'differs' => Icons.compare_arrows,
      _ => Icons.help_outline,
    };

/// One arithmetic result line: "2.5 × 95.00 = 237.50 · printed 237.50".
class LineCheckSummary extends StatelessWidget {
  const LineCheckSummary({super.key, required this.check, required this.currency, this.quantity, this.unitPrice});

  final LineCheck check;
  final String? currency;
  final String? quantity;
  final String? unitPrice;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[];
    if (check.computed != null && quantity != null && unitPrice != null) {
      parts.add('${groupDecimal(quantity!)} × ${formatInvoiceAmount(unitPrice, currency)} = '
          '${formatInvoiceAmount(check.computed, currency)}');
    } else if (check.computed != null) {
      parts.add('Calculated ${formatInvoiceAmount(check.computed, currency)}');
    }
    parts.add('printed ${formatInvoiceAmount(check.printed, currency)}');
    if (check.status == 'differs' && check.difference != null) {
      parts.add('difference ${formatInvoiceAmount(check.difference, currency)}');
    }
    final reasons = check.reasons.map(_reasonText).toList();
    final color = _statusColor(check.status);
    return Semantics(
      label: 'Arithmetic: ${_checkStatusLabel(check.status)}. ${parts.join(', ')}'
          '${reasons.isEmpty ? '' : '. Because ${reasons.join(', ')}'}',
      excludeSemantics: true,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_statusIcon(check.status), size: 18, color: color),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${_checkStatusLabel(check.status)}: ${parts.join(' · ')}',
                    style: TextStyle(color: color, fontWeight: FontWeight.w600)),
                if (reasons.isNotEmpty) Text('Because ${reasons.join(', ')}.'),
                for (final n in check.notes) Text(n, style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Sums (line total, subtotal, tax as printed, total) checked by the server.
class TotalsPanel extends StatelessWidget {
  const TotalsPanel({super.key, required this.checks});

  final ArithmeticChecks checks;

  @override
  Widget build(BuildContext context) {
    final cur = checks.currency;
    Widget row(String label, TotalCheck check) {
      final color = _statusColor(check.status);
      final reasons = check.reasons.map(_reasonText).toList();
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Semantics(
          label: '$label: printed ${formatInvoiceAmount(check.printed, cur)}, '
              'calculated ${formatInvoiceAmount(check.computed, cur)}. ${_checkStatusLabel(check.status)}'
              '${check.status == 'differs' ? ', difference ${formatInvoiceAmount(check.difference, cur)}' : ''}',
          excludeSemantics: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(_statusIcon(check.status), size: 18, color: color),
                  const SizedBox(width: 6),
                  Expanded(child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600))),
                  Text(_checkStatusLabel(check.status), style: TextStyle(color: color, fontWeight: FontWeight.w600)),
                ],
              ),
              Padding(
                padding: const EdgeInsets.only(left: 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Printed: ${formatInvoiceAmount(check.printed, cur)}'),
                    Text('Calculated: ${formatInvoiceAmount(check.computed, cur)}'),
                    if (check.status == 'differs') Text('Difference: ${formatInvoiceAmount(check.difference, cur)}'),
                    if (reasons.isNotEmpty) Text('Cannot fully check because ${reasons.join(', ')}.'),
                    for (final n in check.notes) Text(n, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }

    final currencyText = switch (checks.currencyStatus) {
      'stated' => 'Currency: ${checks.currency} (as printed)',
      'stated_on_lines' => 'Currency: ${checks.currency} (printed on the lines)',
      'missing' => 'Currency: not stated — totals are not calculated and no currency is assumed',
      'mixed' => 'Currency: more than one (${checks.lineCurrencies.join(', ')}) — totals are not calculated',
      _ => 'Currency: not recognised — totals are not calculated',
    };

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(currencyText),
            if (checks.roundingPolicyText != null)
              Text(checks.roundingPolicyText!, style: Theme.of(context).textTheme.bodySmall),
            const Divider(),
            Text('Lines add up to: ${formatInvoiceAmount(checks.linesSum, cur)}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            row('Subtotal', checks.subtotal),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Tax: ${switch (checks.taxSource) {
                    'printed_total' => formatInvoiceAmount(checks.taxPrinted, cur),
                    'tax_lines' => '${formatInvoiceAmount(checks.taxPrinted, cur)} (from the tax lines)',
                    'unreadable' => 'printed but hard to read',
                    _ => 'not printed',
                  }}', style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (checks.taxNote != null) Text(checks.taxNote!, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
            row('Total', checks.total),
          ],
        ),
      ),
    );
  }
}

/// The deterministic plain-language explanation: lines and glossary, sums,
/// comparison with the accepted scope, duplicates, obligations, limitations.
class ExplanationView extends StatelessWidget {
  const ExplanationView({super.key, required this.explanation, required this.lines, this.onShowLine});

  final InvoiceExplanation explanation;
  final List<InvoiceLine> lines;
  final ValueChanged<String>? onShowLine;

  @override
  Widget build(BuildContext context) {
    final c = explanation.content;
    final cur = c.arithmetic.currency;
    final byId = {for (final l in lines) l.id: l};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (c.provisional) const ProvisionalBanner(),
        const SectionHeading('What each line is', subtitle: 'Plain-language descriptions of the lines as printed'),
        for (final l in c.lines)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('Line ${l.lineNumber} · ${lineKindLabels[l.kind] ?? l.kind}',
                            style: Theme.of(context).textTheme.titleSmall),
                      ),
                      if (l.needsConfirmation) const NeedsConfirmationChip(),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(l.plainLanguage),
                  if (l.glossary.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final g in l.glossary)
                          Tooltip(
                            message: g.meaning,
                            child: Chip(
                              label: Text('${g.term}: ${g.meaning}'),
                              visualDensity: VisualDensity.compact,
                            ),
                          ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 6),
                  LineCheckSummary(
                    check: l.arithmetic,
                    currency: cur,
                    quantity: byId[l.lineId]?.quantity,
                    unitPrice: byId[l.lineId]?.unitPrice,
                  ),
                  for (final r in l.relatedToJob)
                    Text(r.type == 'reported_problem'
                        ? 'Relates to the reported problem: ${r.name ?? ''}'
                        : 'Relates to the preparation item: ${r.name ?? ''}${r.status == null ? '' : ' (${r.status})'}'),
                  if (l.region != null && onShowLine != null)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: () => onShowLine!('line:${l.lineId}'),
                        icon: const Icon(Icons.find_in_page_outlined, size: 18),
                        label: Text('Show line ${l.lineNumber} on the document'),
                      ),
                    )
                  else if (l.page != null)
                    Text('Source: page ${l.page}', style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ),
        if (c.lines.isEmpty) const Card(child: ListTile(title: Text('No lines yet.'))),
        const SectionHeading('Checking the sums', subtitle: 'Calculated exactly from the figures printed'),
        TotalsPanel(checks: c.arithmetic),
        const SectionHeading('Compared with the accepted scope'),
        ComparisonPanel(comparison: c.comparison, currency: cur),
        if (c.duplicates.isNotEmpty) ...[
          const SectionHeading('Lines that look the same'),
          for (final d in c.duplicates)
            Card(
              child: ListTile(
                leading: const Icon(Icons.help_outline),
                title: Text('Lines ${d.lineNumbers.join(' and ')}'),
                subtitle: Text(d.note),
              ),
            ),
        ],
        const SectionHeading('Warranties and follow-up', subtitle: 'As stated on the invoice'),
        if (c.obligations.isEmpty)
          const Card(child: ListTile(title: Text('No warranty or follow-up terms were found on the invoice.')))
        else
          for (final o in c.obligations)
            Card(
              child: ListTile(
                leading: Icon(o.kind == 'warranty' ? Icons.verified_outlined : Icons.event_repeat),
                title: Text(o.text),
                subtitle: Text('${o.kind == 'warranty' ? 'Warranty' : 'Follow-up'} · Source: ${o.sourceLabel}'
                    '${o.note == null ? '' : '\n${o.note}'}'),
                isThreeLine: o.note != null,
              ),
            ),
        const SectionHeading('Limitations'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (c.provisional)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 6),
                    child: Text('Provisional until reviewed: these results use details you have not yet confirmed.'),
                  ),
                for (final l in c.limitations)
                  Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('• $l')),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class ComparisonPanel extends StatelessWidget {
  const ComparisonPanel({super.key, required this.comparison, required this.currency});

  final ScopeComparison comparison;
  final String? currency;

  @override
  Widget build(BuildContext context) {
    if (!comparison.available) {
      return Card(
        child: ListTile(
          leading: const Icon(Icons.info_outline),
          title: const Text('Comparison unavailable'),
          subtitle: Text(comparison.message ?? 'There is nothing on record to compare with.'),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (comparison.provisional)
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Text('Provisional until you mark the invoice reviewed.'),
          ),
        for (final item in comparison.items)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('Line ${item.lineNumber}: ${item.description ?? 'no description'}',
                            style: Theme.of(context).textTheme.titleSmall),
                      ),
                      _ComparisonStatus(item: item),
                    ],
                  ),
                  if (item.comparisonUnavailable) ...[
                    const SizedBox(height: 4),
                    const Text('This line can’t be compared with the accepted scope, so it is not counted as a match:'),
                    for (final r in item.unavailableReasons)
                      Padding(
                        padding: const EdgeInsets.only(left: 8, top: 2),
                        child: Text('•  ${comparisonUnavailableReasonText(r)}'),
                      ),
                    if (item.unavailableReasons.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(left: 8, top: 2),
                        child: Text('•  A value needed for the comparison is missing or unreadable.'),
                      ),
                  ],
                  for (final d in item.differences)
                    Text('${d.label}: invoice ${d.field == 'quantity' || d.field == 'currency' ? (d.invoice ?? 'not shown') : formatInvoiceAmount(d.invoice, currency)}'
                        ' · accepted scope ${d.field == 'quantity' || d.field == 'currency' ? (d.approved ?? 'not shown') : formatInvoiceAmount(d.approved, currency)}'),
                  if (item.approvalText != null) ...[
                    const SizedBox(height: 4),
                    Text(item.approvalText!,
                        style: TextStyle(
                            color: item.approval == null && item.status != 'not_compared'
                                ? HelmTheme.warning
                                : HelmTheme.mutedText)),
                  ],
                  if (item.approval != null)
                    Text('Approval record: owner decision on ${item.approval!.decidedAt.substring(0, 10)}'
                        '${item.approval!.scopeLineDescription == null ? '' : ' for “${item.approval!.scopeLineDescription}”'}',
                        style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ),
        if (comparison.notInvoiced.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text('In the accepted scope but not on this invoice:', style: Theme.of(context).textTheme.titleSmall),
          for (final n in comparison.notInvoiced)
            ListTile(
              dense: true,
              leading: const Icon(Icons.remove_circle_outline),
              title: Text(n.description ?? 'No description'),
              subtitle: Text('Scope revision ${n.scopeRevisionNumber} · ${formatInvoiceAmount(n.amount, currency)}'),
            ),
        ],
      ],
    );
  }
}

class _ComparisonStatus extends StatelessWidget {
  const _ComparisonStatus({required this.item});

  final ComparisonItem item;

  @override
  Widget build(BuildContext context) {
    final (label, color, icon) = switch (item.status) {
      'matches' => ('Matches the accepted scope', HelmTheme.success, Icons.check_circle_outline),
      'differs' => ('Differs from the accepted scope', HelmTheme.warning, Icons.compare_arrows),
      'not_in_accepted_scope' => ('Additional — not in the accepted scope', HelmTheme.warning, Icons.add_circle_outline),
      'comparison_unavailable' => ('Can’t compare — a value is missing or unreadable', HelmTheme.warning, Icons.help_outline),
      _ => ('Not compared', HelmTheme.mutedText, Icons.remove),
    };
    return Flexible(child: InfoPill(label: label, color: color, icon: icon));
  }
}
