import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';
import 'package:helm_marine/features/invoices/providers/invoice_providers.dart';

/// `/invoices/new?vessel_id=…&job_id=…` — "Understand an invoice": choose a PDF
/// or photo, upload it privately, then read it into a draft you check. Works
/// standalone (from My Vessel) or linked to your own service job.
class InvoiceUploadScreen extends ConsumerStatefulWidget {
  const InvoiceUploadScreen({super.key, this.vesselId, this.jobId});

  final String? vesselId;
  final String? jobId;

  @override
  ConsumerState<InvoiceUploadScreen> createState() => _InvoiceUploadScreenState();
}

class _InvoiceUploadScreenState extends ConsumerState<InvoiceUploadScreen> {
  final _title = TextEditingController(text: 'Invoice');
  PickedDocument? _doc;

  /// One Idempotency-Key per chosen file: a retry reuses it (no second upload).
  String? _uploadKey;
  String? _status;
  Object? _error;
  bool _busy = false;

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  String get _titleText => _title.text.trim().isEmpty ? 'Invoice' : _title.text.trim();

  Future<void> _pick() async {
    try {
      final doc = await ref.read(documentPickerProvider)();
      if (doc != null && mounted) {
        setState(() {
          _doc = doc;
          _uploadKey = null;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _uploadAndRead() async {
    final doc = _doc;
    if (doc == null || _busy) return;
    final api = ref.read(invoicesApiProvider);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final key = _uploadKey ??= newIdempotencyKey('invoice-upload');
      final asset = await uploadDocument(
        api: api,
        document: doc,
        createIntent: () => api.invoiceIntent(
          jobId: widget.jobId,
          filename: doc.name,
          contentType: doc.contentType,
          sizeBytes: doc.size,
          idempotencyKey: key,
        ),
        pollInterval: ref.read(invoicePollIntervalProvider),
        pollAttempts: ref.read(invoicePollAttemptsProvider),
        onStage: (s) => mounted ? setState(() => _status = s.label) : null,
      );
      setState(() => _status = 'Creating the invoice');
      final invoice = await api.create(assetId: asset.id, jobId: widget.jobId, title: _titleText);
      if (invoice.extraction.available && invoice.canExtract) {
        setState(() => _status = 'Starting to read the invoice');
        try {
          await api.extract(invoice.id, idempotencyKey: newIdempotencyKey('extract'));
        } catch (e) {
          // Reading unavailable: the invoice screen offers manual entry.
          if (ApiError.from(e)?.code != 'extraction_unavailable') rethrow;
        }
      }
      _uploadKey = null;
      ref.invalidate(invoiceListProvider);
      if (mounted) context.go('/invoices/${invoice.id}');
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _manual() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _status = 'Creating the invoice';
    });
    try {
      final invoice = await ref.read(invoicesApiProvider).create(jobId: widget.jobId, title: _titleText);
      ref.invalidate(invoiceListProvider);
      if (mounted) context.go('/invoices/${invoice.id}/review');
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final linked = widget.jobId != null;
    final doc = _doc;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Understand an invoice'),
        leading: BackButton(
          onPressed: () => context.go(widget.vesselId != null ? '/vessels/${widget.vesselId}' : '/invoices'),
        ),
      ),
      body: ContentWidth(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
                'Upload the invoice as a PDF or a photo. Helm reads it into a draft for you to check, explains each '
                'line in plain language, checks the sums and helps you ask factual questions. The file stays private '
                'to you.'),
            const SizedBox(height: 12),
            Card(
              color: HelmTheme.ocean.withValues(alpha: 0.06),
              child: ListTile(
                leading: Icon(linked ? Icons.link : Icons.link_off),
                title: Text(linked ? 'Linked to your service job' : 'Not linked to a service job'),
                subtitle: Text(linked
                    ? 'The invoice can be compared with the job’s accepted scope, and you can choose to send '
                        'questions to the assigned contractor.'
                    : 'You get the explanation and the sums. There is no accepted scope to compare with and no '
                        'contractor to send questions to, and nobody else gets access.'),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _title,
              enabled: !_busy,
              decoration: const InputDecoration(labelText: 'Name for this invoice', helperText: 'For example “Haul-out March”'),
              maxLength: 200,
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 56,
              child: OutlinedButton.icon(
                onPressed: _busy ? null : _pick,
                icon: const Icon(Icons.attach_file),
                label: Text(doc == null ? 'Choose a PDF or photo' : 'Choose a different file'),
              ),
            ),
            if (doc != null)
              Card(
                child: ListTile(
                  leading: Icon(doc.contentType == 'application/pdf' ? Icons.picture_as_pdf_outlined : Icons.image_outlined),
                  title: Text(doc.name),
                  subtitle: Text('${(doc.size / 1024).toStringAsFixed(doc.size < 10240 ? 1 : 0)} KB'),
                ),
              ),
            const SizedBox(height: 12),
            SizedBox(
              height: 56,
              child: FilledButton.icon(
                onPressed: doc == null || _busy ? null : _uploadAndRead,
                icon: const Icon(Icons.cloud_upload_outlined),
                label: const Text('Upload and read'),
              ),
            ),
            if (_busy && _status != null) ...[
              const SizedBox(height: 16),
              Semantics(
                liveRegion: true,
                child: Row(
                  children: [
                    const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 3)),
                    const SizedBox(width: 12),
                    Expanded(child: Text('$_status…')),
                  ],
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 16),
              Card(
                color: HelmTheme.error.withValues(alpha: 0.06),
                child: ListTile(
                  leading: const Icon(Icons.error_outline, color: HelmTheme.error),
                  title: const Text('That didn’t work'),
                  subtitle: Text(describeError(_error!)),
                ),
              ),
            ],
            const Divider(height: 40),
            const Text('No document, or it won’t upload?'),
            const SizedBox(height: 8),
            SizedBox(
              height: 48,
              child: TextButton.icon(
                onPressed: _busy ? null : _manual,
                icon: const Icon(Icons.keyboard_outlined),
                label: const Text('Enter the details by hand instead'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
