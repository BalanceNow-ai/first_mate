import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/session/session.dart';

/// Server limit on a chat message (`AI_MAX_MESSAGE_CHARS`, default 2000); the
/// server's 422 `message_too_long` remains authoritative.
const maxChatMessageChars = 2000;

/// First Mate API (`/ai/*`), scoped to the signed-in user (rebuilt on user change).
final firstMateApiProvider = Provider<FirstMateApi>((ref) {
  ref.watch(currentUserIdProvider);
  return FirstMateApi(ref.watch(dioProvider));
});

class FirstMateApi {
  FirstMateApi(this._dio);

  final Dio _dio;

  Future<T> _call<T>(Future<Response<dynamic>> Function() send, T Function(dynamic) parse) async {
    try {
      return parse((await send()).data);
    } on DioException catch (e) {
      throw ApiError.from(e)!;
    }
  }

  static Map<String, dynamic> _map(dynamic d) => (d as Map).cast<String, dynamic>();

  /// `POST /ai/chat`. Uses [vesselId] (must be the user's), else the
  /// conversation's vessel, else the primary vessel.
  Future<ChatReply> chat({required String message, String? vesselId, String? conversationId}) => _call(
        () => _dio.post('/ai/chat', data: {
          'message': message,
          'vessel_id': ?vesselId,
          'conversation_id': ?conversationId,
        }),
        (d) => ChatReply.fromJson(_map(d)),
      );

  Future<List<ConversationSummary>> conversations() => _call(
        () => _dio.get('/ai/conversations'),
        (d) => [for (final c in d as List) ConversationSummary.fromJson(_map(c))],
      );

  Future<ConversationDetail> conversation(String id) => _call(
        () => _dio.get('/ai/conversations/$id'),
        (d) => ConversationDetail.fromJson(_map(d)),
      );

  Future<void> deleteConversation(String id) => _call(() => _dio.delete('/ai/conversations/$id'), (_) {});

  /// `GET /ai/specialists` (public): specialist domains, also the knowledge domains.
  Future<List<SpecialistInfo>> specialists() => _call(
        () => _dio.get('/ai/specialists'),
        (d) => [for (final s in d as List) SpecialistInfo.fromJson(_map(s))],
      );
}
