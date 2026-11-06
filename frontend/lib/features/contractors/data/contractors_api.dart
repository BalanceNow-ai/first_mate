import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';

/// Contractor organizations API (`/contractors/*`), scoped to the signed-in user.
final contractorsApiProvider = Provider<ContractorsApi>((ref) {
  ref.watch(currentUserIdProvider);
  return ContractorsApi(ref.watch(dioProvider));
});

class ContractorsApi {
  ContractorsApi(this._dio);

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

  /// Active organizations an owner can invite (a listing grants no access).
  Future<List<DirectoryEntry>> directory({String? query, int limit = 20}) => _call(
        () => _dio.get('/contractors/directory', queryParameters: {
          if (query != null && query.trim().isNotEmpty) 'q': query.trim(),
          'limit': limit,
        }),
        (d) => _list(d, DirectoryEntry.fromJson),
      );

  /// My active memberships (empty for people outside any organization).
  Future<List<MyMembership>> myMemberships() =>
      _call(() => _dio.get('/contractors/me'), (d) => _list(d, MyMembership.fromJson));

  Future<ContractorInbox> inbox() =>
      _call(() => _dio.get('/contractors/me/jobs'), (d) => ContractorInbox.fromJson(_map(d)));

  Future<List<InvitationSummary>> orgInvitations(String orgId, {String? status}) => _call(
        () => _dio.get('/contractors/organizations/$orgId/invitations', queryParameters: {'status': ?status}),
        (d) => _list(d, InvitationSummary.fromJson),
      );

  Future<List<OrgMember>> orgMembers(String orgId) =>
      _call(() => _dio.get('/contractors/organizations/$orgId/members'), (d) => _list(d, OrgMember.fromJson));

  Future<InvitationSummary> accept(String assignmentId, List<String> memberUserIds) => _call(
        () => _dio.post('/contractors/assignments/$assignmentId/accept', data: {'member_user_ids': memberUserIds}),
        (d) => InvitationSummary.fromJson(_map(d)),
      );

  Future<InvitationSummary> decline(String assignmentId) => _call(
        () => _dio.post('/contractors/assignments/$assignmentId/decline'),
        (d) => InvitationSummary.fromJson(_map(d)),
      );

  Future<InvitationSummary> addAssignmentMember(String assignmentId, String userId) => _call(
        () => _dio.post('/contractors/assignments/$assignmentId/members', data: {'user_id': userId}),
        (d) => InvitationSummary.fromJson(_map(d)),
      );

  Future<InvitationSummary> removeAssignmentMember(String assignmentId, String userId) => _call(
        () => _dio.delete('/contractors/assignments/$assignmentId/members/$userId'),
        (d) => InvitationSummary.fromJson(_map(d)),
      );
}
