import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/session/session.dart';

/// Crew Rewards API (`/loyalty/*`), scoped to the signed-in user.
final loyaltyApiProvider = Provider<LoyaltyApi>((ref) {
  ref.watch(currentUserIdProvider);
  return LoyaltyApi(ref.watch(dioProvider));
});

class LoyaltyApi {
  LoyaltyApi(this._dio);

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

  Future<PointsSummary> points() => _call(() => _dio.get('/loyalty/points'), (d) => PointsSummary.fromJson(_map(d)));

  Future<TransactionPage> transactions({int limit = 20, int offset = 0}) => _call(
        () => _dio.get('/loyalty/transactions', queryParameters: {'limit': limit, 'offset': offset}),
        (d) => TransactionPage.fromJson(_map(d)),
      );

  Future<MultiplierProgress> multiplier() =>
      _call(() => _dio.get('/loyalty/multiplier'), (d) => MultiplierProgress.fromJson(_map(d)));

  /// The user's crew, or `null` when they are not in one (404 `not_in_crew`).
  Future<Crew?> myCrew() async {
    try {
      return await _call(() => _dio.get('/loyalty/crews/mine'), (d) => Crew.fromJson(_map(d)));
    } on ApiError catch (e) {
      if (e.code == 'not_in_crew') return null;
      rethrow;
    }
  }

  Future<Crew> createCrew(String name) =>
      _call(() => _dio.post('/loyalty/crews', data: {'name': name}), (d) => Crew.fromJson(_map(d)));

  Future<LeaveResult> leaveCrew() =>
      _call(() => _dio.post('/loyalty/crews/mine/leave'), (d) => LeaveResult.fromJson(_map(d)));

  Future<void> removeMember(String userId) =>
      _call(() => _dio.delete('/loyalty/crews/mine/members/$userId'), (_) {});

  Future<List<CrewInvite>> crewInvites() =>
      _call(() => _dio.get('/loyalty/crews/mine/invites'), (d) => _list(d, CrewInvite.fromJson));

  Future<CrewInvite> invite(String email) => _call(
        () => _dio.post('/loyalty/crews/mine/invites', data: {'email': email}),
        (d) => CrewInvite.fromJson(_map(d)),
      );

  Future<CrewInvite> revokeInvite(String id) =>
      _call(() => _dio.delete('/loyalty/crews/mine/invites/$id'), (d) => CrewInvite.fromJson(_map(d)));

  Future<List<MyInvite>> myInvites() => _call(() => _dio.get('/loyalty/invites'), (d) => _list(d, MyInvite.fromJson));

  Future<Crew> acceptInvite(String id) =>
      _call(() => _dio.post('/loyalty/invites/$id/accept'), (d) => Crew.fromJson(_map(d)));

  Future<MyInvite> declineInvite(String id) =>
      _call(() => _dio.post('/loyalty/invites/$id/decline'), (d) => MyInvite.fromJson(_map(d)));

  /// Spends own points (a multiple of 100) for a single-use discount. The
  /// idempotency key makes a double tap return the same entitlement.
  Future<Entitlement> redeemDiscount(int points, {required String idempotencyKey}) => _call(
        () => _dio.post('/loyalty/redeem/discount',
            data: {'points': points}, options: Options(headers: {'Idempotency-Key': idempotencyKey})),
        (d) => Entitlement.fromJson(_map(d)),
      );

  Future<List<Entitlement>> entitlements() =>
      _call(() => _dio.get('/loyalty/entitlements'), (d) => _list(d, Entitlement.fromJson));

  Future<Entitlement> voidEntitlement(String id) =>
      _call(() => _dio.post('/loyalty/entitlements/$id/void'), (d) => Entitlement.fromJson(_map(d)));

  Future<ExperienceCatalogue> experiences() =>
      _call(() => _dio.get('/loyalty/experiences'), (d) => ExperienceCatalogue.fromJson(_map(d)));

  Future<Redemption> redeemExperience(String experienceId, {String? note}) => _call(
        () => _dio.post('/loyalty/redeem/experience', data: {
          'experience_id': experienceId,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
        (d) => Redemption.fromJson(_map(d)),
      );

  Future<List<Redemption>> redemptions() =>
      _call(() => _dio.get('/loyalty/redemptions'), (d) => _list(d, Redemption.fromJson));
}
