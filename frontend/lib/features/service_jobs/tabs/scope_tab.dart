import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Parses a typed dollar amount ("95", "95.5", "1,234.50") into integer minor
/// units without floating point; null when it is not a valid amount.
int? parseMinorUnits(String text) {
  final t = text.trim().replaceAll(',', '').replaceAll(r'$', '');
  final m = RegExp(r'^(\d{1,9})(?:\.(\d{1,2}))?$').firstMatch(t);
  if (m == null) return null;
  final cents = (m.group(2) ?? '').padRight(2, '0');
  return int.parse(m.group(1)!) * 100 + int.parse(cents);
}

/// Scope revisions and the owner's explicit decision on one exact revision.
class ScopeTab extends ConsumerWidget {
  const ScopeTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scopes = ref.watch(scopesProvider(job.id));
    final owner = job.viewer.isOwner;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        InfoNote(owner
            ? 'Only you can accept a scope, and each decision applies to one exact revision. A change needs a new '
                'decision. Nothing here pays or books anything.'
            : 'Propose the work and any estimate as a revision. A later change is a new revision the owner must decide on '
                'separately.'),
        AsyncSection<List<ScopeRevision>>(
          value: scopes,
          onRetry: () => ref.invalidate(scopesProvider(job.id)),
          builder: (list) {
            final current = list.where((s) => s.isCurrent).firstOrNull;
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (!owner && !job.isClosed)
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: ActionButton(
                    label: current == null ? 'Propose a scope' : 'Propose a change',
                    icon: Icons.post_add,
                    filled: true,
                    onPressed: () async {
                      final input = await showDialog<ScopeInput>(
                        context: context,
                        builder: (_) => ScopeDialog(supersedes: current),
                      );
                      if (input == null || !context.mounted) return;
                      await runJobAction(context, ref, job.id, () => ref.read(serviceJobsApiProvider).proposeScope(job.id, input),
                          success: 'Scope revision sent to the owner');
                    },
                  ),
                ),
              if (list.isEmpty) const Text('No scope proposed yet.'),
              for (final s in list.reversed) _ScopeCard(job: job, scope: s),
            ]);
          },
        ),
      ],
    );
  }
}

class _ScopeCard extends ConsumerWidget {
  const _ScopeCard({required this.job, required this.scope});

  final ServiceJob job;
  final ScopeRevision scope;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = scope;
    final currency = s.currency ?? 'NZD';
    final tone = switch (s.status) {
      'accepted' => Tone.good,
      'rejected' => Tone.bad,
      'change_requested' => Tone.warn,
      'superseded' => Tone.neutral,
      _ => Tone.info,
    };
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      color: s.isCurrent ? null : HelmTheme.surface,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Semantics(
                header: true,
                child: Text('Revision ${s.revisionNumber}${s.isChange ? ' (change)' : ''}',
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
            StatusBadge(scopeStatusLabel(s.status), tone: tone, semanticPrefix: 'Scope'),
          ]),
          const SizedBox(height: 6),
          Text(s.summary),
          if (s.tasks.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text('Tasks', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final t in s.tasks)
              Text('• ${t['description']}${t['needs_site_inspection'] == true ? ' (needs site inspection)' : ''}'),
          ],
          if (s.estimateLines.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text('Estimate', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final l in s.estimateLines)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(children: [
                  Expanded(
                    child: Text('${l.description} · ${estimateKindLabel(l.kind)}'
                        '${l.quantity != null && l.unitPriceMinor != null ? ' · ${l.quantity}${l.unit == null ? '' : ' ${l.unit}'} × ${formatCents(l.unitPriceMinor!, currency: currency)}' : ''}'),
                  ),
                  Text(formatCents(l.amountMinor, currency: currency)),
                ]),
              ),
            if (s.estimateTotalMinor != null)
              Row(children: [
                const Expanded(child: Text('Estimate total', style: TextStyle(fontWeight: FontWeight.bold))),
                Text(formatCents(s.estimateTotalMinor!, currency: currency, showCode: true),
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ]),
            const Text('An estimate, not an invoice. Tax is shown only if the contractor included it.',
                style: TextStyle(fontSize: 12, color: HelmTheme.mutedText)),
          ],
          if (s.exclusions != null) FactRow('Not included', s.exclusions!),
          if (s.assumptions != null) FactRow('Assumptions', s.assumptions!),
          FactRow('Proposed', formatDateTime(s.createdAt)),
          if (s.decision != null)
            FactRow('Your decision',
                '${decisionLabel(s.decision!.decision)} on ${formatDateTime(s.decision!.decidedAt)}'
                '${s.decision!.note == null ? '' : ' — “${s.decision!.note}”'}'),
          if (job.viewer.isOwner && s.isCurrent && s.isOpen && !job.isClosed) ...[
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, children: [
              ActionButton(
                label: 'Accept revision ${s.revisionNumber}',
                icon: Icons.check_circle_outline,
                filled: true,
                onPressed: () => _decide(context, ref, 'accepted'),
              ),
              ActionButton(
                label: 'Request a change',
                icon: Icons.edit_note,
                onPressed: () => _decide(context, ref, 'change_requested'),
              ),
              ActionButton(
                label: 'Reject',
                icon: Icons.cancel_outlined,
                tone: Tone.bad,
                onPressed: () => _decide(context, ref, 'rejected'),
              ),
            ]),
          ],
        ]),
      ),
    );
  }

  Future<void> _decide(BuildContext context, WidgetRef ref, String decision) async {
    final s = scope;
    final verb = switch (decision) {
      'accepted' => 'Accept',
      'rejected' => 'Reject',
      _ => 'Request a change to',
    };
    final note = await promptText(
      context,
      title: '$verb revision ${s.revisionNumber}?',
      label: decision == 'change_requested' ? 'What should change?' : 'Note (optional)',
      message: 'This decision applies to revision ${s.revisionNumber} exactly as shown '
          '(reference ${s.contentDigest.substring(0, 8)}). If it changes, you will be asked again.',
      required: decision == 'change_requested',
      confirm: decision == 'accepted' ? 'Accept this revision' : 'Send decision',
    );
    if (note == null || !context.mounted) return;
    await runJobAction(
      context,
      ref,
      job.id,
      () => ref
          .read(serviceJobsApiProvider)
          .decideScope(job.id, s, decision, note: note, idempotencyKey: newIdempotencyKey('scope')),
      success: '${decisionLabel(decision)}: revision ${s.revisionNumber}',
    );
  }
}

class _LineControllers {
  final description = TextEditingController();
  String kind = 'labour';
  final quantity = TextEditingController();
  final unit = TextEditingController();
  final unitPrice = TextEditingController();
  final amount = TextEditingController();
}

/// Contractor: propose a scope revision with tasks and estimate lines.
class ScopeDialog extends StatefulWidget {
  const ScopeDialog({super.key, this.supersedes});

  final ScopeRevision? supersedes;

  @override
  State<ScopeDialog> createState() => _ScopeDialogState();
}

class _ScopeDialogState extends State<ScopeDialog> {
  final _form = GlobalKey<FormState>();
  late final _summary = TextEditingController(text: widget.supersedes?.summary);
  late final _tasks = TextEditingController(
      text: widget.supersedes?.tasks.map((t) => '${t['description']}').join('\n'));
  late final _exclusions = TextEditingController(text: widget.supersedes?.exclusions);
  late final _assumptions = TextEditingController(text: widget.supersedes?.assumptions);
  final List<_LineControllers> _lines = [_LineControllers()];

  String? _money(String? v) => v == null || v.trim().isEmpty || parseMinorUnits(v) != null ? null : 'Enter dollars and cents, e.g. 95.00';
  String? _qty(String? v) =>
      v == null || v.trim().isEmpty || RegExp(r'^\d+(\.\d{1,4})?$').hasMatch(v.trim()) ? null : 'Use a number such as 1.5';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.supersedes == null ? 'Propose a scope' : 'Propose a change to revision ${widget.supersedes!.revisionNumber}'),
      content: SizedBox(
        width: 560,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              TextFormField(
                controller: _summary,
                maxLines: 2,
                maxLength: 4000,
                decoration: const InputDecoration(labelText: 'Summary of the work *'),
                validator: (v) => v == null || v.trim().isEmpty ? 'Summarise the work' : null,
              ),
              TextFormField(
                controller: _tasks,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Tasks (one per line; end with “?” if it needs site inspection)',
                ),
              ),
              const SizedBox(height: 12),
              const Text('Estimate lines (NZD)', style: TextStyle(fontWeight: FontWeight.bold)),
              for (final (i, l) in _lines.indexed) _lineEditor(i, l),
              TextButton.icon(
                onPressed: () => setState(() => _lines.add(_LineControllers())),
                icon: const Icon(Icons.add),
                label: const Text('Add an estimate line'),
              ),
              TextFormField(controller: _exclusions, maxLines: 2, decoration: const InputDecoration(labelText: 'Not included')),
              TextFormField(controller: _assumptions, maxLines: 2, decoration: const InputDecoration(labelText: 'Assumptions')),
            ]),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _submit, child: const Text('Send to the owner')),
      ],
    );
  }

  Widget _lineEditor(int i, _LineControllers l) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(border: Border.all(color: Colors.black12), borderRadius: BorderRadius.circular(8)),
      child: Column(children: [
        Row(children: [
          Expanded(
            child: TextFormField(
              controller: l.description,
              decoration: InputDecoration(labelText: 'Line ${i + 1} description'),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 150,
            child: DropdownButtonFormField<String>(
              isExpanded: true,
              initialValue: l.kind,
              decoration: const InputDecoration(labelText: 'Kind'),
              items: [for (final e in estimateKindLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
              onChanged: (v) => setState(() => l.kind = v ?? l.kind),
            ),
          ),
        ]),
        Wrap(spacing: 8, children: [
          SizedBox(width: 100, child: TextFormField(controller: l.quantity, decoration: const InputDecoration(labelText: 'Qty'), validator: _qty)),
          SizedBox(width: 100, child: TextFormField(controller: l.unit, decoration: const InputDecoration(labelText: 'Unit'))),
          SizedBox(
            width: 130,
            child: TextFormField(controller: l.unitPrice, decoration: const InputDecoration(labelText: 'Unit price \$'), validator: _money),
          ),
          SizedBox(
            width: 130,
            child: TextFormField(controller: l.amount, decoration: const InputDecoration(labelText: 'Or amount \$'), validator: _money),
          ),
        ]),
      ]),
    );
  }

  void _submit() {
    if (!_form.currentState!.validate()) return;
    final lines = <EstimateLineInput>[];
    for (final l in _lines) {
      if (l.description.text.trim().isEmpty) continue;
      final unitPrice = parseMinorUnits(l.unitPrice.text);
      final amount = parseMinorUnits(l.amount.text);
      final hasQty = l.quantity.text.trim().isNotEmpty;
      if (amount == null && !(hasQty && unitPrice != null)) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Line “${l.description.text.trim()}” needs an amount, or a quantity and unit price')));
        return;
      }
      lines.add(EstimateLineInput(
        description: l.description.text,
        kind: l.kind,
        quantity: hasQty ? l.quantity.text : null,
        unit: l.unit.text,
        unitPriceMinor: unitPrice,
        amountMinor: amount,
      ));
    }
    final tasks = [
      for (final t in _tasks.text.split('\n'))
        if (t.trim().isNotEmpty)
          (
            description: t.trim().endsWith('?') ? t.trim().substring(0, t.trim().length - 1) : t.trim(),
            needsSiteInspection: t.trim().endsWith('?'),
          ),
    ];
    Navigator.pop(
      context,
      ScopeInput(
        summary: _summary.text,
        tasks: tasks,
        estimateLines: lines,
        currency: lines.isEmpty ? null : 'NZD',
        exclusions: _exclusions.text,
        assumptions: _assumptions.text,
        supersedesId: widget.supersedes?.id,
      ),
    );
  }
}
