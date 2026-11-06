import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';

/// The signed-in owner's invoices, newest first (optionally for one job).
final invoiceListProvider = FutureProvider.autoDispose.family<List<InvoiceSummary>, String?>((ref, jobId) {
  final api = ref.watch(invoicesApiProvider);
  requireUserId(ref);
  return api.list(jobId: jobId);
});

/// One invoice. Every mutation replaces the state with the server's detail
/// response; nothing is computed on the device.
final invoiceControllerProvider =
    AsyncNotifierProvider.autoDispose.family<InvoiceController, InvoiceDetail, String>(InvoiceController.new);

class InvoiceController extends AsyncNotifier<InvoiceDetail> {
  InvoiceController(this.invoiceId);

  final String invoiceId;

  InvoicesApi get _api => ref.read(invoicesApiProvider);

  @override
  Future<InvoiceDetail> build() {
    final api = ref.watch(invoicesApiProvider);
    requireUserId(ref);
    return api.get(invoiceId);
  }

  void _set(InvoiceDetail detail) {
    if (ref.mounted) state = AsyncData(detail);
  }

  Future<InvoiceDetail> reload() async {
    final detail = await _api.get(invoiceId);
    _set(detail);
    return detail;
  }

  /// Runs a mutation that returns the invoice and stores the result.
  Future<InvoiceDetail> apply(Future<InvoiceDetail> Function(InvoicesApi api, InvoiceDetail current) op) async {
    final current = state.value ?? await future;
    final next = await op(_api, current);
    _set(next);
    return next;
  }

  /// Queues reading of the current revision and waits for the result.
  Future<ExtractionRun> extract() async {
    final run = await _api.extract(invoiceId, idempotencyKey: newIdempotencyKey('extract'));
    return waitForRun(run);
  }

  /// Polls a run until it finishes, then reloads the invoice.
  Future<ExtractionRun> waitForRun(ExtractionRun run) async {
    final interval = ref.read(invoicePollIntervalProvider);
    final attempts = ref.read(invoicePollAttemptsProvider);
    var current = run;
    for (var i = 0; current.inProgress && i < attempts && ref.mounted; i++) {
      await Future<void>.delayed(interval);
      if (!ref.mounted) return current;
      current = await _api.extractionRun(invoiceId, run.id);
    }
    if (ref.mounted) await reload();
    return current;
  }

  /// Builds (or refreshes) the explanation and reloads the invoice with it.
  Future<InvoiceDetail> explain() async {
    await _api.explain(invoiceId);
    return reload();
  }

  Future<void> createQuestion({required String text, String? lineId, String? suggestionKey}) async {
    await _api.createQuestion(invoiceId, text: text, lineId: lineId, suggestionKey: suggestionKey);
    await reload();
  }

  Future<void> updateQuestion(InvoiceQuestion q, String text) async {
    await _api.updateQuestion(invoiceId, q.id, expectedVersion: q.version, text: text);
    await reload();
  }

  Future<void> deleteQuestion(InvoiceQuestion q) async {
    await _api.deleteQuestion(invoiceId, q.id, expectedVersion: q.version);
    await reload();
  }

  Future<void> sendQuestion(InvoiceQuestion q, List<String> assetIds) async {
    await _api.sendQuestion(invoiceId, q.id,
        expectedVersion: q.version, assetIds: assetIds, idempotencyKey: newIdempotencyKey('send'));
    await reload();
  }
}
