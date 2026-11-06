import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';
import 'package:helm_marine/features/invoices/widgets/document_viewer.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';

/// Invoice questions the owner explicitly sent to your organization's
/// assignment on a job (only those, with only the documents they chose).
final contractorInvoiceQuestionsProvider =
    FutureProvider.autoDispose.family<List<SharedInvoiceQuestion>, String>((ref, jobId) {
  final api = ref.watch(invoicesApiProvider);
  requireUserId(ref);
  return api.contractorQuestions(jobId);
});

/// `/contractor/jobs/:jobId/invoice-questions` — for the assigned contractor.
class ContractorInvoiceQuestionsScreen extends ConsumerWidget {
  const ContractorInvoiceQuestionsScreen({super.key, required this.jobId});

  final String jobId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final questions = ref.watch(contractorInvoiceQuestionsProvider(jobId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Invoice questions'),
        leading: BackButton(onPressed: () => context.canPop() ? context.pop() : context.go('/')),
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(contractorInvoiceQuestionsProvider(jobId).future),
        child: ContentWidth(
          maxWidth: 820,
          child: questions.when(
            loading: () => const LoadingView(message: 'Loading questions…'),
            error: (e, _) {
              final api = ApiError.from(e);
              final title = switch (api?.statusCode) {
                403 when api?.code == 'section_not_shared' =>
                  'The owner hasn’t shared invoice questions on this job with you',
                403 => 'This page is for the contractor assigned to the job',
                404 => 'Job not found',
                _ => 'Could not load the questions',
              };
              return ErrorView(
                error: e,
                title: title,
                onRetry: api?.statusCode == 403 || api?.statusCode == 404
                    ? null
                    : () => ref.invalidate(contractorInvoiceQuestionsProvider(jobId)),
              );
            },
            data: (items) => ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                    'The owner chose to send you these questions about their invoice, with the documents shown. '
                    'Your reply is attributed to you and your organization. A corrected invoice you attach becomes a '
                    'new revision; the original is never changed.'),
                const SizedBox(height: 12),
                if (items.isEmpty)
                  const Card(
                    child: ListTile(
                      leading: Icon(Icons.inbox_outlined),
                      title: Text('No invoice questions for this job'),
                    ),
                  ),
                for (final q in items) _SharedQuestionCard(jobId: jobId, question: q),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SharedQuestionCard extends ConsumerStatefulWidget {
  const _SharedQuestionCard({required this.jobId, required this.question});

  final String jobId;
  final SharedInvoiceQuestion question;

  @override
  ConsumerState<_SharedQuestionCard> createState() => _SharedQuestionCardState();
}

class _SharedQuestionCardState extends ConsumerState<_SharedQuestionCard> {
  final _form = GlobalKey<FormState>();
  final _reply = TextEditingController();
  PickedDocument? _correction;
  String? _status;
  bool _busy = false;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    try {
      final doc = await ref.read(documentPickerProvider)();
      if (doc != null && mounted) setState(() => _correction = doc);
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e);
    }
  }

  Future<void> _send() async {
    if (!_form.currentState!.validate() || _busy) return;
    final api = ref.read(invoicesApiProvider);
    setState(() => _busy = true);
    try {
      String? correctedAssetId;
      final doc = _correction;
      if (doc != null) {
        final key = newIdempotencyKey('correction');
        final asset = await uploadDocument(
          api: api,
          document: doc,
          createIntent: () => api.jobDocumentIntent(
            widget.jobId,
            filename: doc.name,
            contentType: doc.contentType,
            sizeBytes: doc.size,
            caption: 'Corrected invoice',
            idempotencyKey: key,
          ),
          pollInterval: ref.read(invoicePollIntervalProvider),
          pollAttempts: ref.read(invoicePollAttemptsProvider),
          onStage: (s) => mounted ? setState(() => _status = s.label) : null,
        );
        correctedAssetId = asset.id;
      }
      setState(() => _status = 'Sending your reply');
      await api.respond(widget.jobId, widget.question.id, text: _reply.text.trim(), correctedAssetId: correctedAssetId);
      _reply.clear();
      setState(() => _correction = null);
      ref.invalidate(contractorInvoiceQuestionsProvider(widget.jobId));
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Reply sent to the owner.')));
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e);
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _status = null;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final q = widget.question;
    final line = q.line;
    final api = ref.read(invoicesApiProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _form,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${q.invoiceTitle}${q.invoiceRevisionNumber == null ? '' : ' · revision ${q.invoiceRevisionNumber}'}',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  InfoPill(
                    label: q.status == 'answered' ? 'Answered' : 'Waiting for your reply',
                    color: q.status == 'answered' ? HelmTheme.success : HelmTheme.ocean,
                  ),
                ],
              ),
              if (q.sharedAt != null)
                Text('Sent by the owner ${formatWhen(q.sharedAt!)}', style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              Text('Question from the owner', style: Theme.of(context).textTheme.labelMedium),
              Text(q.text),
              if (line != null) ...[
                const SizedBox(height: 8),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  color: HelmTheme.surface,
                  child: Text(
                    'Line ${line.lineNumber} · ${lineKindLabels[line.kind] ?? line.kind}: ${line.description ?? 'no description'}'
                    '${line.quantity == null ? '' : ' · quantity ${formatQuantity(line.quantity, line.unit)}'}'
                    '${line.unitPrice == null ? '' : ' · unit price ${formatInvoiceAmount(line.unitPrice, line.currency)}'}'
                    ' · amount ${formatInvoiceAmount(line.lineTotal, line.currency)}'
                    '${line.page == null ? '' : ' · page ${line.page}'}',
                  ),
                ),
              ],
              const SizedBox(height: 8),
              Text('Documents shared with this question', style: Theme.of(context).textTheme.labelMedium),
              if (q.sharedAssets.isEmpty) const Text('None.'),
              for (final a in q.sharedAssets)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(a.isPdf ? Icons.picture_as_pdf_outlined : Icons.image_outlined),
                  title: Text(a.label),
                  trailing: TextButton.icon(
                    onPressed: () => openDocumentLink(context, () => api.sharedAssetUrl(widget.jobId, q.id, a.id)),
                    icon: const Icon(Icons.open_in_new, size: 18),
                    label: const Text('Open'),
                  ),
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
                        '${r.authorRole == 'contractor' ? 'Reply from your organization' : 'From the owner'} · '
                        '${formatWhen(r.createdAt)}',
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                      Text(r.text),
                      if (r.correctedRevisionId != null) const Text('A corrected invoice was attached.'),
                    ],
                  ),
                ),
              const Divider(height: 24),
              TextFormField(
                controller: _reply,
                enabled: !_busy,
                minLines: 2,
                maxLines: 6,
                maxLength: 4000,
                decoration: const InputDecoration(labelText: 'Your reply to the owner'),
                validator: (v) => (v ?? '').trim().isEmpty ? 'Write a reply' : null,
              ),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _pick,
                    icon: const Icon(Icons.attach_file),
                    label: Text(_correction == null ? 'Attach a corrected invoice (optional)' : 'Choose a different file'),
                  ),
                  if (_correction != null)
                    InputChip(
                      label: Text(_correction!.name),
                      onDeleted: _busy ? null : () => setState(() => _correction = null),
                      deleteButtonTooltipMessage: 'Remove the attachment',
                    ),
                ],
              ),
              const SizedBox(height: 12),
              if (_busy && _status != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Semantics(liveRegion: true, child: Text('$_status…')),
                ),
              SizedBox(
                height: 48,
                child: FilledButton.icon(
                  onPressed: _busy ? null : _send,
                  icon: const Icon(Icons.reply),
                  label: const Text('Send reply'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
