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
import 'package:helm_marine/features/invoices/widgets/questions_panel.dart';

/// `/invoices/:id` — status, reading progress, the explanation, questions and
/// revision history of one of your invoices.
class InvoiceDetailScreen extends ConsumerStatefulWidget {
  const InvoiceDetailScreen({super.key, required this.invoiceId});

  final String invoiceId;

  @override
  ConsumerState<InvoiceDetailScreen> createState() => _InvoiceDetailScreenState();
}

class _InvoiceDetailScreenState extends ConsumerState<InvoiceDetailScreen> {
  bool _polling = false;
  bool _explaining = false;
  bool _working = false;
  String? _pollingRunId;

  InvoiceController get _controller => ref.read(invoiceControllerProvider(widget.invoiceId).notifier);

  /// Keeps polling while a reading run for the current revision is in progress
  /// (e.g. after the upload screen queued it, or after a page reload).
  void _maybePoll(InvoiceDetail detail) {
    final run = detail.currentRun;
    if (run == null || !run.inProgress || _polling || _pollingRunId == run.id) return;
    _pollingRunId = run.id;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      setState(() => _polling = true);
      try {
        await _controller.waitForRun(run);
      } catch (_) {
        // The panel shows the latest state; the user can retry.
      } finally {
        if (mounted) setState(() => _polling = false);
      }
    });
  }

  Future<void> _extract() async {
    setState(() => _polling = true);
    try {
      await _controller.extract();
    } catch (e) {
      if (mounted) await showMutationError(context, e, onReload: () => _controller.reload());
    } finally {
      if (mounted) setState(() => _polling = false);
    }
  }

  Future<void> _explain() async {
    setState(() => _explaining = true);
    try {
      await _controller.explain();
    } catch (e) {
      if (mounted) await showMutationError(context, e, onReload: () => _controller.reload());
    } finally {
      if (mounted) setState(() => _explaining = false);
    }
  }

  Future<void> _delete(InvoiceDetail inv) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this invoice?'),
        content: const Text(
            'The invoice, its explanation and your draft questions are removed from Helm. Questions you already '
            'sent are closed. Copies someone else already downloaded can’t be recalled.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: HelmTheme.error),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete invoice'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _working = true);
    try {
      await ref.read(invoicesApiProvider).delete(inv.id, expectedVersion: inv.summary.version);
      ref.invalidate(invoiceListProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Invoice deleted.')));
        context.go('/invoices');
      }
    } catch (e) {
      if (mounted) await showMutationError(context, e, onReload: () => _controller.reload());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final invoice = ref.watch(invoiceControllerProvider(widget.invoiceId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Invoice'),
        leading: BackButton(onPressed: () => context.go('/invoices')),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: () async {
              if (!invoice.hasValue) return ref.invalidate(invoiceControllerProvider(widget.invoiceId));
              try {
                await _controller.reload();
              } catch (e) {
                if (context.mounted) showErrorSnackBar(context, e);
              }
            },
            icon: const Icon(Icons.refresh),
          ),
          if (invoice.hasValue)
            IconButton(
              tooltip: 'Delete invoice',
              onPressed: _working ? null : () => _delete(invoice.requireValue),
              icon: const Icon(Icons.delete_outline),
            ),
        ],
      ),
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
        data: (inv) {
          _maybePoll(inv);
          return RefreshIndicator(
            onRefresh: () => _controller.reload(),
            child: ContentWidth(
              maxWidth: 900,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _Header(invoice: inv),
                  _ExtractionPanel(
                    invoice: inv,
                    polling: _polling,
                    onExtract: _extract,
                    onManual: () => context.go('/invoices/${inv.id}/review'),
                  ),
                  if (inv.provisional && inv.lines.isNotEmpty)
                    ProvisionalBanner(onReview: () => context.go('/invoices/${inv.id}/review')),
                  if (inv.needsConfirmation.isNotEmpty)
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.warning_amber_rounded, color: HelmTheme.warning),
                        title: Text('${inv.needsConfirmation.length} '
                            '${inv.needsConfirmation.length == 1 ? 'value was' : 'values were'} hard to read'),
                        subtitle: const Text('Confirm or correct them against the document.'),
                      ),
                    ),
                  const SizedBox(height: 8),
                  SizedBox(
                    height: 52,
                    child: FilledButton.icon(
                      onPressed: () => context.go('/invoices/${inv.id}/review'),
                      icon: const Icon(Icons.fact_check_outlined),
                      label: Text(inv.provisional ? 'Check and correct the details' : 'View details and document'),
                    ),
                  ),
                  const SectionHeading('Explanation'),
                  if (inv.explanation == null || inv.explanation!.stale)
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.menu_book_outlined),
                        title: Text(inv.explanation == null
                            ? 'Get a plain-language explanation'
                            : 'The invoice changed since the explanation was written'),
                        subtitle: const Text(
                            'Explains each line, checks the sums exactly and compares with any accepted scope. '
                            'Nothing is sent to anyone.'),
                        trailing: _explaining
                            ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 3))
                            : FilledButton(
                                onPressed: _explain,
                                child: Text(inv.explanation == null ? 'Explain this invoice' : 'Refresh explanation'),
                              ),
                      ),
                    ),
                  if (inv.explanation != null && !inv.explanation!.stale)
                    ExplanationView(
                      explanation: inv.explanation!,
                      lines: inv.lines,
                      onShowLine: (key) => context.go('/invoices/${inv.id}/review?select=$key'),
                    ),
                  QuestionsPanel(invoice: inv),
                  _Revisions(invoice: inv),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.invoice});

  final InvoiceDetail invoice;

  @override
  Widget build(BuildContext context) {
    final f = invoice.revision.fields;
    final currency = invoice.revision.currency;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text(invoice.summary.title, style: Theme.of(context).textTheme.titleLarge),
            ),
            const SizedBox(height: 4),
            if (f['supplier_name']?.value != null) Text('From ${f['supplier_name']!.value}'),
            if (f['total']?.value != null)
              Text('Total as printed: ${formatInvoiceAmount(f['total']!.value, currency)}',
                  style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                InfoPill(label: invoiceStatusLabel(invoice.summary.status), color: HelmTheme.ocean),
                InfoPill(
                  label: invoice.standalone ? 'Not linked to a service job' : 'Linked to a service job',
                  color: HelmTheme.mutedText,
                  icon: invoice.standalone ? Icons.link_off : Icons.link,
                ),
                if (invoice.revisions.length > 1)
                  InfoPill(
                    label: 'Revision ${invoice.revision.brief.revisionNumber} of ${invoice.revisions.length}',
                    color: HelmTheme.secondary,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ExtractionPanel extends StatelessWidget {
  const _ExtractionPanel({required this.invoice, required this.polling, required this.onExtract, required this.onManual});

  final InvoiceDetail invoice;
  final bool polling;
  final VoidCallback onExtract;
  final VoidCallback onManual;

  @override
  Widget build(BuildContext context) {
    final rev = invoice.revision;
    final ext = invoice.extraction;
    final run = invoice.currentRun;
    Widget card(IconData icon, Color color, String title, String body, {Widget? action}) => Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Semantics(
              liveRegion: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Icon(icon, color: color),
                    const SizedBox(width: 8),
                    Expanded(child: Text(title, style: Theme.of(context).textTheme.titleSmall)),
                  ]),
                  const SizedBox(height: 4),
                  Text(body),
                  if (action != null) ...[const SizedBox(height: 8), action],
                ],
              ),
            ),
          ),
        );

    final substituteNote = ext.substitute && rev.extractionStatus != 'none'
        ? Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              'Read by the local test reader (a development substitute). It shows how the flow works, not how '
              'accurately real invoices are read — please check every value.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          )
        : null;

    if (polling || (run?.inProgress ?? false)) {
      return card(Icons.document_scanner_outlined, HelmTheme.ocean, 'Reading the invoice…',
          'This usually takes a few seconds. You can leave this page; the result is kept.',
          action: const LinearProgressIndicator());
    }
    if (rev.brief.sourceAssetId == null) {
      return card(Icons.keyboard_outlined, HelmTheme.mutedText, 'Entered by hand',
          'There is no document for this revision. Add the lines and totals yourself.',
          action: OutlinedButton(onPressed: onManual, child: const Text('Enter the details')));
    }
    if (rev.extractionStatus == 'unreadable') {
      return card(
        Icons.help_outline,
        HelmTheme.warning,
        'This document couldn’t be read automatically',
        '${rev.extractionNotes.isEmpty ? 'No invoice text was found.' : rev.extractionNotes.join(' ')} '
            'Enter the details yourself while looking at the document.',
        action: OutlinedButton(onPressed: onManual, child: const Text('Enter the details')),
      );
    }
    if (run != null && run.failed && invoice.canExtract) {
      return card(Icons.error_outline, HelmTheme.error, 'Reading didn’t finish',
          'Automatic reading failed this time. Try again, or enter the details yourself.',
          action: Wrap(spacing: 8, children: [
            FilledButton(onPressed: ext.available ? onExtract : null, child: const Text('Try again')),
            OutlinedButton(onPressed: onManual, child: const Text('Enter the details')),
          ]));
    }
    if (invoice.canExtract) {
      if (!ext.available) {
        return card(Icons.cloud_off, HelmTheme.warning, 'Automatic reading is unavailable',
            ext.message ?? 'Automatic invoice reading is unavailable right now. You can enter the details yourself.',
            action: OutlinedButton(onPressed: onManual, child: const Text('Enter the details')));
      }
      final isCorrection = rev.brief.origin == 'contractor_correction';
      return card(
        Icons.document_scanner_outlined,
        HelmTheme.ocean,
        isCorrection ? 'A corrected invoice was attached' : 'Not read yet',
        isCorrection
            ? 'The contractor attached a corrected invoice (revision ${rev.brief.revisionNumber}). Read it to see '
                'its lines; the previous revision and your corrections are kept.'
            : 'Read the document into a draft that you then check.',
        action: Wrap(spacing: 8, runSpacing: 8, children: [
          FilledButton(onPressed: onExtract, child: const Text('Read this document')),
          OutlinedButton(onPressed: onManual, child: const Text('Enter the details instead')),
        ]),
      );
    }
    if (rev.extractionStatus == 'extracted') {
      final unavailableNow = !ext.available
          ? Text(ext.message ?? 'Automatic reading is unavailable right now.',
              style: Theme.of(context).textTheme.bodySmall)
          : null;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          card(
            Icons.task_alt,
            HelmTheme.success,
            invoice.provisional ? 'Read into a draft' : 'Reviewed',
            invoice.provisional
                ? 'Check the values against the document — especially any marked “Needs your confirmation”.'
                : 'You reviewed the details${rev.reviewedAt == null ? '' : ' on ${rev.reviewedAt!.substring(0, 10)}'}.',
            action: substituteNote ?? unavailableNow,
          ),
        ],
      );
    }
    return const SizedBox.shrink();
  }
}

class _Revisions extends StatelessWidget {
  const _Revisions({required this.invoice});

  final InvoiceDetail invoice;

  @override
  Widget build(BuildContext context) {
    if (invoice.revisions.length < 2) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionHeading('Revisions',
            subtitle: 'A corrected invoice becomes a new revision. Earlier revisions are kept unchanged.'),
        for (final r in invoice.revisions.reversed)
          Card(
            child: ListTile(
              leading: Icon(r.id == invoice.revision.id ? Icons.radio_button_checked : Icons.history),
              title: Text('Revision ${r.revisionNumber}${r.id == invoice.revision.id ? ' (current)' : ''}'),
              subtitle: Text('${r.originLabel} · ${invoiceStatusLabel(r.status)} · ${formatWhen(r.createdAt)}'),
              trailing: r.sourceAssetId == null
                  ? null
                  : _OpenRevisionDocument(assetId: r.sourceAssetId!, revisionNumber: r.revisionNumber),
            ),
          ),
      ],
    );
  }
}

class _OpenRevisionDocument extends ConsumerWidget {
  const _OpenRevisionDocument({required this.assetId, required this.revisionNumber});

  final String assetId;
  final int revisionNumber;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      tooltip: 'Open the revision $revisionNumber document',
      icon: const Icon(Icons.open_in_new),
      onPressed: () => openDocumentLink(context, () => ref.read(invoicesApiProvider).downloadUrl(assetId)),
    );
  }
}
