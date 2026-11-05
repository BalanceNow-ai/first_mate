import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/admin.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/session/session.dart';

/// Minimum confidence the server requires to verify a fitment rule
/// (`FITMENT_MIN_CONFIDENCE`, default 0.7). The server's 422 is authoritative.
const minFitmentConfidence = 0.7;

/// Admin curation API. Every endpoint requires the `admin` role on the server;
/// a 403 is surfaced as-is.
final adminApiProvider = Provider<AdminApi>((ref) {
  ref.watch(currentUserIdProvider);
  return AdminApi(ref.watch(dioProvider));
});

class AdminApi {
  AdminApi(this._dio);

  final Dio _dio;

  Future<T> _call<T>(Future<Response<dynamic>> Function() send, T Function(dynamic) parse) async {
    try {
      return parse((await send()).data);
    } on DioException catch (e) {
      throw ApiError.from(e)!;
    }
  }

  static Map<String, dynamic> _map(dynamic d) => (d as Map).cast<String, dynamic>();
  static List<T> _list<T>(dynamic d, T Function(Map<String, dynamic>) f) => [for (final e in d as List) f(_map(e))];

  // --- Fitment rules ---
  Future<List<FitmentRule>> fitmentRules({String? status = 'unverified', int limit = 100}) => _call(
        () => _dio.get('/products/fitment-rules', queryParameters: {'verification_status': ?status, 'limit': limit}),
        (d) => _list(d, FitmentRule.fromJson),
      );

  Future<FitmentRule> verifyFitmentRule(String id, {required double confidence, String? notes, String? sourceUrl}) =>
      _call(
        () => _dio.post('/products/fitment-rules/$id/verify', data: {
          'confidence_score': confidence,
          if (notes != null && notes.trim().isNotEmpty) 'notes': notes.trim(),
          if (sourceUrl != null && sourceUrl.trim().isNotEmpty) 'source_url': sourceUrl.trim(),
        }),
        (d) => FitmentRule.fromJson(_map(d)),
      );

  Future<FitmentRule> rejectFitmentRule(String id, {String? notes}) => _call(
        () => _dio.post('/products/fitment-rules/$id/reject',
            data: {if (notes != null && notes.trim().isNotEmpty) 'notes': notes.trim()}),
        (d) => FitmentRule.fromJson(_map(d)),
      );

  // --- Equipment profile verification ---
  Future<List<VerificationRequest>> verificationRequests({String status = 'pending'}) => _call(
        () => _dio.get('/boat-db/verification-requests', queryParameters: {'status': status}),
        (d) => _list(d, VerificationRequest.fromJson),
      );

  Future<VerificationRequest> reviewVerification(String id, {required bool approve, String? note}) => _call(
        () => _dio.post('/boat-db/verification-requests/$id/${approve ? 'approve' : 'reject'}',
            data: {if (note != null && note.trim().isNotEmpty) 'review_note': note.trim()}),
        (d) => VerificationRequest.fromJson(_map(d)),
      );

  // --- Knowledge corpus ---
  Future<List<KnowledgeSource>> knowledgeSources({String? status}) => _call(
        () => _dio.get('/knowledge/sources', queryParameters: {'status': ?status, 'limit': 200}),
        (d) => _list(d, KnowledgeSource.fromJson),
      );

  Future<KnowledgeIngestResult> ingest(KnowledgeIngestDraft draft) =>
      _call(() => _dio.post('/knowledge/sources', data: draft.toJson()), (d) => KnowledgeIngestResult.fromJson(_map(d)));

  Future<KnowledgeSource> admit(String id, {bool? licenceVerified}) => _call(
        () => _dio.post('/knowledge/sources/$id/admit',
            data: licenceVerified == null ? null : {'licence_verified': licenceVerified}),
        (d) => KnowledgeSource.fromJson(_map(d)),
      );

  Future<KnowledgeSource> revoke(String id) =>
      _call(() => _dio.post('/knowledge/sources/$id/revoke'), (d) => KnowledgeSource.fromJson(_map(d)));

  Future<KnowledgeReembedResult> reembed(String id) =>
      _call(() => _dio.post('/knowledge/sources/$id/reembed'), (d) => KnowledgeReembedResult.fromJson(_map(d)));

  Future<void> deleteSource(String id) => _call(() => _dio.delete('/knowledge/sources/$id'), (_) {});

  // --- Experience redemptions ---
  Future<List<Redemption>> redemptions({String? status}) => _call(
        () => _dio.get('/loyalty/admin/redemptions', queryParameters: {'status': ?status}),
        (d) => _list(d, Redemption.fromJson),
      );

  /// [action] is `confirm`, `fulfil` or `cancel` (cancel restores the points).
  Future<Redemption> redemptionAction(String id, String action, {String? staffNote}) => _call(
        () => _dio.post('/loyalty/admin/redemptions/$id/$action',
            data: {if (staffNote != null && staffNote.trim().isNotEmpty) 'staff_note': staffNote.trim()}),
        (d) => Redemption.fromJson(_map(d)),
      );

  // --- Users & roles ---
  Future<List<User>> users({String? email, String? role}) => _call(
        () => _dio.get('/admin/users', queryParameters: {
          if (email != null && email.trim().isNotEmpty) 'email': email.trim(),
          'role': ?role,
          'limit': 100,
        }),
        (d) => _list(d, User.fromJson),
      );

  Future<User> setRole(String userId, String role) =>
      _call(() => _dio.put('/admin/users/$userId/role', data: {'role': role}), (d) => User.fromJson(_map(d)));

  // --- Audit ---
  Future<List<AuditEntry>> audit({String? entityType}) => _call(
        () => _dio.get('/admin/audit', queryParameters: {
          if (entityType != null && entityType.isNotEmpty) 'entity_type': entityType,
          'limit': 200,
        }),
        (d) => _list(d, AuditEntry.fromJson),
      );
}
