import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/providers/invoice_providers.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';
import 'package:helm_marine/features/invoices/widgets/value_editors.dart';

/// Suggested factual questions → editable private drafts → an explicit Send
/// (job-linked invoices only) → attributed replies. Nothing is ever sent
/// automatically.
class QuestionsPanel extends ConsumerStatefulWidget {
  const QuestionsPanel({super.key, required this.invoice});

  final InvoiceDetail invoice;

  @override
  ConsumerState<QuestionsPanel> createState() => _QuestionsPanelState();
}

class _QuestionsPanelState extends ConsumerState<QuestionsPanel> {
  bool _busy = false;

  InvoiceController get _controller => ref.read(invoiceControllerProvider(widget.invoice.id).notifier);

  Future<void> _run(Future<void> Function() op, {String? done}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await op();
      if (mounted && done != null) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      }
    } on _Handled {
      // Already explained to the person.
    } catch (e) {
      if (mounted) await showMutationError(context, e, onReload: () => _controller.reload());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _draftFrom(SuggestedQuestion s) async {
    final text = await showQuestionEditor(context, title: 'Edit the suggested question', initial: s.text);
    if (text == null) return;
    await _run(() => _controller.createQuestion(text: text, lineId: s.lineId, suggestionKey: s.key),
        done: 'Draft saved. It has not been sent.');
  }

  Future<void> _writeOwn() async {
    final text = await showQuestionEditor(context, title: 'Write a question');
    if (text == null) return;
    await _run(() => _controller.createQuestion(text: text), done: 'Draft saved. It has not been sent.');
  }

  Future<void> _edit(InvoiceQuestion q) async {
    final text = await showQuestionEditor(context, title: 'Edit your draft', initial: q.text);
    if (text == null || text == q.text) return;
    await _run(() => _controller.updateQuestion(q, text), done: 'Draft updated.');
  }

  Future<void> _delete(InvoiceQuestion q) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this draft?'),
        content: const Text('The draft has not been sent, so nobody else has seen it.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete draft')),
        ],
      ),
    );
    if (ok == true) await _run(() => _controller.deleteQuestion(q), done: 'Draft deleted.');
  }

  Future<void> _send(InvoiceQuestion q) async {
    final docs = <String, String>{
      for (final r in widget.invoice.revisions)
        if (r.sourceAssetId != null) r.sourceAssetId!: 'Revision ${r.revisionNumber} document (${r.originLabel})',
    };
    final chosen = await showDialog<List<String>>(
      context: context,
      builder: (context) => _SendDialog(question: q, documents: docs),
    );
    if (chosen == null) return;
    await _run(() async {
      try {
        await _controller.sendQuestion(q, chosen);
      } catch (e) {
        if (ApiError.from(e)?.code == 'invoices_section_not_shared' && widget.invoice.summary.jobId != null) {
          if (mounted) await _offerSharing(widget.invoice.summary.jobId!);
          throw const _Handled();
        }
        rethrow;
      }
    }, done: 'Question sent to the assigned contractor.');
  }

  /// The contractor can't receive invoice questions until the owner shares that section.
  Future<void> _offerSharing(String jobId) async {
    final edit = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Invoice questions aren’t shared with this contractor'),
        content: const Text(
            'The contractor on this job can only receive invoice questions if you add “Invoice questions you choose '
            'to share” to what they can see. Your draft is kept and nothing has been sent.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Not now')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Edit sharing')),
        ],
      ),
    );
    if (edit == true && mounted) GoRouter.of(context).go('/service-jobs/$jobId/sharing');
  }

  @override
  Widget build(BuildContext context) {
    final inv = widget.invoice;
    final suggestions = inv.explanation?.content.suggestedQuestions ?? const <SuggestedQuestion>[];
    final drafted = {for (final q in inv.questions) q.text};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionHeading('Questions for the contractor',
            subtitle: 'Suggested questions are only drafts. You edit them, and nothing is sent unless you press Send.'),
        if (inv.standalone)
          const Card(
            child: ListTile(
              leading: Icon(Icons.link_off),
              title: Text('Sharing isn’t available for this invoice'),
              subtitle: Text(
                  'It isn’t linked to a service job with an assigned contractor, so questions can’t be sent from '
                  'Helm. You can still draft them here and ask the supplier yourself.'),
            ),
          ),
        if (suggestions.isNotEmpty) ...[
          Text('Suggested questions', style: Theme.of(context).textTheme.titleSmall),
          for (final (i, s) in suggestions.indexed)
            Card(
              child: ListTile(
                leading: const Icon(Icons.lightbulb_outline),
                title: Text(s.text),
                trailing: drafted.any((t) => t.startsWith(s.text))
                    ? const InfoPill(label: 'Drafted', color: HelmTheme.success, icon: Icons.check)
                    : TextButton(
                        onPressed: _busy ? null : () => _draftFrom(s),
                        child: Text('Edit and save', semanticsLabel: 'Edit and save suggestion ${i + 1}'),
                      ),
              ),
            ),
        ] else if (inv.explanation == null)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 4),
            child: Text('Explain the invoice to see suggested questions.'),
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _writeOwn,
            icon: const Icon(Icons.edit_note),
            label: const Text('Write your own question'),
          ),
        ),
        const SizedBox(height: 8),
        if (inv.questions.isNotEmpty) Text('Your questions', style: Theme.of(context).textTheme.titleSmall),
        for (final q in inv.questions)
          _QuestionCard(
            question: q,
            invoice: inv,
            busy: _busy,
            onEdit: () => _edit(q),
            onDelete: () => _delete(q),
            onSend: inv.standalone ? null : () => _send(q),
          ),
      ],
    );
  }
}

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({
    required this.question,
    required this.invoice,
    required this.busy,
    required this.onEdit,
    required this.onDelete,
    required this.onSend,
  });

  final InvoiceQuestion question;
  final InvoiceDetail invoice;
  final bool busy;
  final VoidCallback onEdit;
  final VoidCallback onDelete;
  final VoidCallback? onSend;

  @override
  Widget build(BuildContext context) {
    final q = question;
    final line = invoice.lines.where((l) => l.id == q.lineId).firstOrNull;
    final revisionNumbers = {for (final r in invoice.revisions) r.id: r.revisionNumber};
    final statusColor = switch (q.status) {
      'draft' => HelmTheme.mutedText,
      'answered' => HelmTheme.success,
      _ => HelmTheme.ocean,
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                InfoPill(label: q.statusLabel, color: statusColor),
                if (line != null) InfoPill(label: 'About line ${line.lineNumber}', color: HelmTheme.ocean),
              ],
            ),
            const SizedBox(height: 6),
            Text(q.text),
            if (q.sharedAt != null)
              Text(
                'Sent ${formatWhen(q.sharedAt!)} with ${q.sharedAssetIds.length} '
                '${q.sharedAssetIds.length == 1 ? 'document' : 'documents'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            for (final r in q.responses)
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: HelmTheme.surface,
                  border: Border(left: BorderSide(color: HelmTheme.secondary.withValues(alpha: 0.8), width: 3)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      r.authorRole == 'contractor'
                          ? 'Reply from the assigned contractor · ${formatWhen(r.createdAt)}'
                          : 'Your note · ${formatWhen(r.createdAt)}',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(r.text),
                    if (r.correctedRevisionId != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          'Attached a corrected invoice — revision '
                          '${revisionNumbers[r.correctedRevisionId] ?? ''}. The original and your corrections are kept.',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                  ],
                ),
              ),
            if (q.isDraft) ...[
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  OutlinedButton.icon(
                    onPressed: busy ? null : onEdit,
                    icon: const Icon(Icons.edit_outlined, size: 18),
                    label: const Text('Edit'),
                  ),
                  OutlinedButton.icon(
                    onPressed: busy ? null : onDelete,
                    icon: const Icon(Icons.delete_outline, size: 18),
                    label: const Text('Delete draft'),
                  ),
                  if (onSend != null)
                    FilledButton.icon(
                      onPressed: busy ? null : onSend,
                      icon: const Icon(Icons.send, size: 18),
                      label: const Text('Send to the contractor…'),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SendDialog extends StatefulWidget {
  const _SendDialog({required this.question, required this.documents});

  final InvoiceQuestion question;
  final Map<String, String> documents;

  @override
  State<_SendDialog> createState() => _SendDialogState();
}

class _SendDialogState extends State<_SendDialog> {
  final _selected = <String>{};

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Send this question?'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                  'This sends the question below, and only the documents you tick, to the contractor assigned to '
                  'this job. They can reply or attach a corrected invoice. Copies they download can’t be recalled.'),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                color: HelmTheme.surface,
                child: Text(widget.question.text),
              ),
              const SizedBox(height: 12),
              Text('Documents to include', style: Theme.of(context).textTheme.titleSmall),
              if (widget.documents.isEmpty) const Text('This invoice has no document to share.'),
              for (final e in widget.documents.entries)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _selected.contains(e.key),
                  onChanged: (v) => setState(() => v == true ? _selected.add(e.key) : _selected.remove(e.key)),
                  title: Text(e.value),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton.icon(
          onPressed: () => Navigator.pop(context, _selected.toList()),
          icon: const Icon(Icons.send, size: 18),
          label: const Text('Send'),
        ),
      ],
    );
  }
}

/// An error already explained to the person (no further message).
class _Handled implements Exception {
  const _Handled();
}
