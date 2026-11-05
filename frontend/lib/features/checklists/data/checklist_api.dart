import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/checklist.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/products/data/api_call.dart';

/// Checklist API scoped to the signed-in user.
final checklistApiProvider = Provider<ChecklistApi>((ref) {
  ref.watch(currentUserIdProvider);
  return ChecklistApi(ref.watch(dioProvider));
});

/// Export formats of `GET /checklists/vessel/{id}/export`.
enum ExportFormat {
  html('html', 'text/html'),
  csv('csv', 'text/csv');

  const ExportFormat(this.wire, this.mimeType);

  final String wire;
  final String mimeType;
}

/// A downloaded export (fetched with the user's token).
class ChecklistExport {
  const ChecklistExport({required this.filename, required this.mimeType, required this.content});

  final String filename;
  final String mimeType;
  final String content;
}

/// Typed access to `/checklists/...`.
class ChecklistApi {
  ChecklistApi(this._dio);

  final Dio _dio;

  Future<ChecklistSet> get(String vesselId) => apiCall(
        () => _dio.get('/checklists/vessel/$vesselId'),
        (d) => ChecklistSet.fromJson(asMap(d)),
      );

  /// Creates the three tiers (409 `checklists_exist` unless [regenerate]).
  Future<ChecklistSet> generate(String vesselId, {bool regenerate = false}) => apiCall(
        () => _dio.post('/checklists/vessel/$vesselId/generate',
            queryParameters: {if (regenerate) 'regenerate': true}),
        (d) => ChecklistSet.fromJson(asMap(d)),
      );

  Future<ChecklistTier> tier(String vesselId, ChecklistTierId tier) => apiCall(
        () => _dio.get('/checklists/vessel/$vesselId/tiers/${tier.wire}'),
        (d) => ChecklistTier.fromJson(asMap(d)),
      );

  Future<void> deleteAll(String vesselId) => apiCall(() => _dio.delete('/checklists/vessel/$vesselId'), (_) {});

  /// Sets the checked ("already on board") state.
  Future<ChecklistItem> setChecked(String itemId, bool checked) => apiCall(
        () => _dio.patch('/checklists/items/$itemId', data: {'is_checked': checked}),
        (d) => ChecklistItem.fromJson(asMap(d)),
      );

  /// Owner-chosen product: 409 `fitment_mismatch` for a verified mismatch;
  /// an unknown fit links with a `warning`.
  Future<ChecklistItem> link(String itemId, String productId) => apiCall(
        () => _dio.put('/checklists/items/$itemId/link', data: {'product_id': productId}),
        (d) => ChecklistItem.fromJson(asMap(d)),
      );

  /// Ensures the cart holds the tier's unchecked linked items (idempotent).
  Future<AddMissingResult> addMissingToCart(String vesselId, ChecklistTierId tier) => apiCall(
        () => _dio.post('/checklists/vessel/$vesselId/add-missing-to-cart', data: {'tier': tier.wire}),
        (d) => AddMissingResult.fromJson(asMap(d)),
      );

  /// Fetches a printable HTML / CSV export with the user's token.
  Future<ChecklistExport> export(String vesselId, ChecklistTierId tier, ExportFormat format) async {
    late Response<String> response;
    await apiCall(
      () async => response = await _dio.get<String>('/checklists/vessel/$vesselId/export',
          queryParameters: {'tier': tier.wire, 'format': format.wire},
          options: Options(responseType: ResponseType.plain, headers: {'Accept': format.mimeType})),
      (_) {},
    );
    final disposition = response.headers.value('content-disposition') ?? '';
    final name = RegExp(r'filename="([^"]+)"').firstMatch(disposition)?.group(1);
    return ChecklistExport(
      filename: name ?? 'checklist-${tier.wire}.${format.wire}',
      mimeType: format.mimeType,
      content: response.data ?? '',
    );
  }
}
