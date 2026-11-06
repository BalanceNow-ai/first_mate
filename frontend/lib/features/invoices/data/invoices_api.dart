import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/orders/data/api_call.dart';

/// Typed client for "Understand my invoice", private invoice/job documents and
/// the assigned contractor's shared invoice questions. A new instance per
/// signed-in user, so every dependant provider resets when the user changes.
final invoicesApiProvider = Provider<InvoicesApi>((ref) {
  ref.watch(currentUserIdProvider);
  return InvoicesApi(ref.watch(dioProvider));
});

/// Fetches a short-lived signed document URL's bytes. The URL already carries
/// its own authorization, so no API token is attached (and none may be).
typedef DocumentBytesFetcher = Future<Uint8List> Function(String url);

final documentBytesFetcherProvider = Provider<DocumentBytesFetcher>((ref) {
  final dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 15),
    receiveTimeout: const Duration(seconds: 60),
    responseType: ResponseType.bytes,
  ));
  ref.onDispose(dio.close);
  return (url) async {
    try {
      final r = await dio.get<List<int>>(url);
      return Uint8List.fromList(r.data ?? const []);
    } on DioException catch (e) {
      throw ApiError.fromDio(e);
    }
  };
});

class InvoicesApi {
  InvoicesApi(this._dio);

  final Dio _dio;

  static Options _key(String key) => Options(headers: {'Idempotency-Key': key});

  // --- invoices ---------------------------------------------------------------

  Future<List<InvoiceSummary>> list({String? jobId}) => apiCall(
        () => _dio.get('/invoices', queryParameters: {'job_id': ?jobId}),
        (d) => [for (final i in asMapList(d)) InvoiceSummary.fromJson(i)],
      );

  Future<InvoiceDetail> get(String id) =>
      apiCall(() => _dio.get('/invoices/$id'), (d) => InvoiceDetail.fromJson(asMap(d)));

  /// Starts an invoice from an available uploaded document, or (no [assetId])
  /// for manual entry. Re-submitting the same document returns that invoice.
  Future<InvoiceDetail> create({String? assetId, String? jobId, required String title}) => apiCall(
        () => _dio.post('/invoices', data: {
          'asset_id': ?assetId,
          'job_id': ?jobId,
          'title': title,
        }),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  Future<void> delete(String id, {int? expectedVersion}) => apiCall(
        () => _dio.delete('/invoices/$id',
            queryParameters: {'expected_version': ?expectedVersion}),
        (_) {},
      );

  /// Queues reading of the current revision's document (asynchronous).
  /// A 503 `extraction_unavailable` means reading is off; manual entry still works.
  Future<ExtractionRun> extract(String id, {required String idempotencyKey}) => apiCall(
        () => _dio.post('/invoices/$id/extract', options: _key(idempotencyKey)),
        (d) => ExtractionRun.fromJson(asMap(d)),
      );

  Future<ExtractionRun> extractionRun(String id, String runId) => apiCall(
        () => _dio.get('/invoices/$id/extraction-runs/$runId'),
        (d) => ExtractionRun.fromJson(asMap(d)),
      );

  /// Corrects/confirms header fields; a `null` value records "not on the invoice".
  Future<InvoiceDetail> correctFields(String id, {required int expectedVersion, required Map<String, String?> changes}) =>
      apiCall(
        () => _dio.patch('/invoices/$id/fields', data: {'expected_version': expectedVersion, ...changes}),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  Future<InvoiceDetail> addLine(String id, {required int expectedVersion, required Map<String, String?> values}) =>
      apiCall(
        () => _dio.post('/invoices/$id/lines', data: {'expected_version': expectedVersion, ...values}),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  /// Corrects one line; sending no changes confirms it as printed.
  Future<InvoiceDetail> correctLine(String id, String lineId,
          {required int expectedVersion, Map<String, String?> changes = const {}}) =>
      apiCall(
        () => _dio.patch('/invoices/$id/lines/$lineId', data: {'expected_version': expectedVersion, ...changes}),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  Future<InvoiceDetail> deleteLine(String id, String lineId, {required int expectedVersion}) => apiCall(
        () => _dio.delete('/invoices/$id/lines/$lineId', queryParameters: {'expected_version': expectedVersion}),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  /// Marks the current revision reviewed, confirming the listed hard-to-read
  /// items as printed (409 `needs_confirmation` if any remain).
  Future<InvoiceDetail> review(String id, {required int expectedVersion, List<String> confirm = const []}) =>
      apiCall(
        () => _dio.post('/invoices/$id/review', data: {'expected_version': expectedVersion, 'confirm': confirm}),
        (d) => InvoiceDetail.fromJson(asMap(d)),
      );

  /// Builds (or returns the unchanged) deterministic explanation. Sends nothing.
  Future<InvoiceExplanation> explain(String id) =>
      apiCall(() => _dio.post('/invoices/$id/explain'), (d) => InvoiceExplanation.fromJson(asMap(d)));

  // --- questions --------------------------------------------------------------

  Future<List<InvoiceQuestion>> questions(String id) => apiCall(
        () => _dio.get('/invoices/$id/questions'),
        (d) => [for (final q in asMapList(d)) InvoiceQuestion.fromJson(q)],
      );

  /// A private draft (yours or an edited suggestion); nothing is sent.
  Future<InvoiceQuestion> createQuestion(String id, {required String text, String? lineId, String? suggestionKey}) =>
      apiCall(
        () => _dio.post('/invoices/$id/questions', data: {
          'text': text,
          'line_id': ?lineId,
          'suggestion_key': ?suggestionKey,
        }),
        (d) => InvoiceQuestion.fromJson(asMap(d)),
      );

  Future<InvoiceQuestion> updateQuestion(String id, String questionId,
          {required int expectedVersion, required String text}) =>
      apiCall(
        () => _dio.patch('/invoices/$id/questions/$questionId',
            data: {'expected_version': expectedVersion, 'text': text}),
        (d) => InvoiceQuestion.fromJson(asMap(d)),
      );

  Future<void> deleteQuestion(String id, String questionId, {int? expectedVersion}) => apiCall(
        () => _dio.delete('/invoices/$id/questions/$questionId',
            queryParameters: {'expected_version': ?expectedVersion}),
        (_) {},
      );

  /// The owner's explicit send to the job's assigned contractor, with the
  /// chosen documents. Refused for a standalone invoice (409 `standalone_invoice`).
  Future<InvoiceQuestion> sendQuestion(String id, String questionId,
          {required int expectedVersion, required List<String> assetIds, required String idempotencyKey}) =>
      apiCall(
        () => _dio.post('/invoices/$id/questions/$questionId/send',
            data: {'expected_version': expectedVersion, 'asset_ids': assetIds}, options: _key(idempotencyKey)),
        (d) => InvoiceQuestion.fromJson(asMap(d)),
      );

  // --- private media ----------------------------------------------------------

  /// Starts an invoice document upload (owner only; optional own job).
  Future<AssetIntent> invoiceIntent({
    String? jobId,
    String? filename,
    String? contentType,
    int? sizeBytes,
    required String idempotencyKey,
  }) =>
      apiCall(
        () => _dio.post('/service-assets/invoice-intents',
            data: {
              'job_id': ?jobId,
              'filename': ?filename,
              'content_type': ?contentType,
              'size_bytes': ?sizeBytes,
            },
            options: _key(idempotencyKey)),
        (d) => AssetIntent.fromJson(asMap(d)),
      );

  /// Starts a job document upload (here: the assigned contractor's corrected invoice).
  Future<AssetIntent> jobDocumentIntent(
    String jobId, {
    String? filename,
    String? contentType,
    int? sizeBytes,
    String? caption,
    required String idempotencyKey,
  }) =>
      apiCall(
        () => _dio.post('/service-jobs/$jobId/assets/intents',
            data: {
              'purpose': 'job_document',
              'filename': ?filename,
              'content_type': ?contentType,
              'size_bytes': ?sizeBytes,
              'caption': ?caption,
            },
            options: _key(idempotencyKey)),
        (d) => AssetIntent.fromJson(asMap(d)),
      );

  /// Sends the raw bytes for an upload intent (the content itself is checked
  /// by the server, whatever it is declared as).
  Future<ServiceAsset> putContent(String assetId, Uint8List bytes) => apiCall(
        () => _dio.put(
          '/service-assets/$assetId/content',
          data: Stream<List<int>>.value(bytes),
          options: Options(
            contentType: 'application/octet-stream',
            headers: {if (!kIsWeb) Headers.contentLengthHeader: bytes.length},
            sendTimeout: kIsWeb ? null : const Duration(minutes: 2),
          ),
        ),
        (d) => ServiceAsset.fromJson(asMap(d)),
      );

  Future<ServiceAsset> asset(String assetId) =>
      apiCall(() => _dio.get('/service-assets/$assetId'), (d) => ServiceAsset.fromJson(asMap(d)));

  /// A short-lived link to the metadata-stripped copy of a document you can see.
  Future<DownloadLink> downloadUrl(String assetId) => apiCall(
        () => _dio.post('/service-assets/$assetId/download-url', data: {'variant': 'derivative'}),
        (d) => DownloadLink.fromAssetJson(asMap(d)),
      );

  // --- contractor -------------------------------------------------------------

  Future<List<SharedInvoiceQuestion>> contractorQuestions(String jobId) => apiCall(
        () => _dio.get('/service-jobs/$jobId/invoice-questions'),
        (d) => [for (final q in asMapList(d)) SharedInvoiceQuestion.fromJson(q)],
      );

  Future<SharedInvoiceQuestion> contractorQuestion(String jobId, String questionId) => apiCall(
        () => _dio.get('/service-jobs/$jobId/invoice-questions/$questionId'),
        (d) => SharedInvoiceQuestion.fromJson(asMap(d)),
      );

  Future<DownloadLink> sharedAssetUrl(String jobId, String questionId, String assetId) => apiCall(
        () => _dio.get('/service-jobs/$jobId/invoice-questions/$questionId/assets/$assetId/download-url'),
        (d) => DownloadLink.fromSignedJson(asMap(d)),
      );

  /// The contractor's attributed answer, optionally with a corrected invoice
  /// (a new revision; the original is never overwritten).
  Future<SharedInvoiceQuestion> respond(String jobId, String questionId,
          {required String text, String? correctedAssetId}) =>
      apiCall(
        () => _dio.post('/service-jobs/$jobId/invoice-questions/$questionId/respond', data: {
          'text': text,
          'corrected_asset_id': ?correctedAssetId,
        }),
        (d) => SharedInvoiceQuestion.fromJson(asMap(d)),
      );
}
