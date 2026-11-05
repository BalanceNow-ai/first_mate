// TODO(client pass 2): move to the First Mate contract (citations, product
// references, explicit cart actions) once the AI workstream is merged.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';
import 'package:helm_marine/core/session/session.dart';

class ChatMessage {
  final String role; // 'user' or 'assistant'
  final String content;
  final DateTime timestamp;

  ChatMessage({
    required this.role,
    required this.content,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();
}

class ChatState {
  final List<ChatMessage> messages;
  final String? conversationId;
  final bool isLoading;
  final String? error;

  const ChatState({
    this.messages = const [],
    this.conversationId,
    this.isLoading = false,
    this.error,
  });

  ChatState copyWith({
    List<ChatMessage>? messages,
    String? conversationId,
    bool? isLoading,
    String? error,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      conversationId: conversationId ?? this.conversationId,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

class ChatNotifier extends StateNotifier<ChatState> {
  final ApiService _apiService;
  final Monitoring _monitoring;
  final String? vesselId;

  ChatNotifier(this._apiService, this._monitoring, {this.vesselId})
      : super(const ChatState());

  Future<void> sendMessage(String text) async {
    final isNewConversation = state.conversationId == null && state.messages.isEmpty;
    final userMessage = ChatMessage(role: 'user', content: text);
    state = state.copyWith(
      messages: [...state.messages, userMessage],
      isLoading: true,
      error: null,
    );

    if (isNewConversation) {
      _monitoring.capture('ai_conversation_started', properties: {
        'has_vessel_context': vesselId != null,
      });
    }

    try {
      final response = await _apiService.sendChatMessage(
        message: text,
        vesselId: vesselId,
        conversationId: state.conversationId,
      );

      final assistantMessage = ChatMessage(
        role: 'assistant',
        content: response['response'] as String? ?? '',
      );

      state = state.copyWith(
        messages: [...state.messages, assistantMessage],
        conversationId:
            response['conversation_id'] as String? ?? state.conversationId,
        isLoading: false,
      );
    } catch (e) {
      state = state.copyWith(
        isLoading: false,
        error: describeError(e),
      );
    }
  }

  void clearConversation() {
    state = const ChatState();
  }
}

/// Provider for chat, optionally scoped to a vessel.
final chatProvider = StateNotifierProvider.autoDispose
    .family<ChatNotifier, ChatState, String?>(
  (ref, vesselId) {
    final apiService = ref.watch(userApiProvider);
    return ChatNotifier(apiService, ref.read(monitoringProvider), vesselId: vesselId);
  },
);

/// Provider for conversation history list.
final conversationListProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.watch(userApiProvider);
  return apiService.getConversations();
});
