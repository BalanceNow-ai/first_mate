import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/moderation/data/moderation_models.dart';
import 'package:helm_marine/features/orders/data/api_call.dart';

final moderationApiProvider = Provider<ModerationApi>((ref) {
  ref.watch(currentUserIdProvider);
  return ModerationApi(ref.watch(dioProvider));
});

/// Case-scoped moderation (moderator or admin role; everyone else gets 403).
class ModerationApi {
  ModerationApi(this._dio);

  final Dio _dio;

  /// [status]: active (open + under review) | open | under_review | resolved | all.
  Future<List<CaseSummary>> cases({String status = 'active', int limit = 50, int offset = 0}) => apiCall(
        () => _dio.get('/moderation/cases', queryParameters: {'status': status, 'limit': limit, 'offset': offset}),
        (d) => [for (final c in asMapList(d)) CaseSummary.fromJson(c)],
      );

  Future<CaseDetail> caseDetail(String id) =>
      apiCall(() => _dio.get('/moderation/cases/$id'), (d) => CaseDetail.fromJson(asMap(d)));

  /// assign | restrict | unrestrict | resolve (resolve needs a [disposition]).
  /// The reason is mandatory and recorded in the audit trail.
  Future<CaseDetail> act(String id, {required String action, required String reason, String? disposition}) =>
      apiCall(
        () => _dio.post('/moderation/cases/$id/actions', data: {
          'action': action,
          'reason': reason,
          'disposition': ?disposition,
        }),
        (d) => CaseDetail.fromJson(asMap(d)),
      );
}
