import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

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
  final String? vesselId;

  ChatNotifier(this._apiService, {this.vesselId}) : super(const ChatState());

  Future<void> sendMessage(String text) async {
    final userMessage = ChatMessage(role: 'user', content: text);
    state = state.copyWith(
      messages: [...state.messages, userMessage],
      isLoading: true,
      error: null,
    );

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
        error: e.toString(),
      );
    }
  }

  void clearConversation() {
    state = const ChatState();
  }
}

/// Provider for chat, optionally scoped to a vessel.
final chatProvider =
    StateNotifierProvider.family<ChatNotifier, ChatState, String?>(
  (ref, vesselId) {
    final apiService = ref.read(apiServiceProvider);
    return ChatNotifier(apiService, vesselId: vesselId);
  },
);

/// Provider for conversation history list.
final conversationListProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getConversations();
});
