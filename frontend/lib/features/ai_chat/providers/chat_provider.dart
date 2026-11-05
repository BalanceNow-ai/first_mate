import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/ai_chat/data/first_mate_api.dart';

/// One message in the visible conversation.
class ChatEntry {
  const ChatEntry.user(this.content, this.createdAt, {this.failed = false})
      : role = 'user',
        turn = null;

  const ChatEntry.assistant(AssistantTurn this.turn)
      : role = 'assistant',
        content = '',
        createdAt = null,
        failed = false;

  final String role;
  final String content;
  final DateTime? createdAt;

  /// The assistant's answer with grounding, citations, products and actions.
  final AssistantTurn? turn;

  /// A user message the server did not accept (shown with a retry).
  final bool failed;

  bool get isUser => role == 'user';
  String get text => turn?.content ?? content;

  ChatEntry markFailed() => ChatEntry.user(content, createdAt, failed: true);
}

class ChatState {
  const ChatState({
    this.messages = const [],
    this.conversationId,
    this.vesselId,
    this.sending = false,
    this.loadingConversation = false,
    this.error,
  });

  final List<ChatEntry> messages;
  final String? conversationId;

  /// The vessel explicitly chosen for context (sent as `vessel_id`); null lets
  /// the server use the conversation's vessel, else the primary vessel.
  final String? vesselId;
  final bool sending;
  final bool loadingConversation;

  /// The last failure (an `ApiError` with the server's `{detail, code}`).
  final Object? error;

  bool get isEmpty => messages.isEmpty;

  /// The vessel the server last answered for (`ChatResponse.vessel`).
  AssistantTurn? get lastTurn {
    for (final m in messages.reversed) {
      if (m.turn != null) return m.turn;
    }
    return null;
  }

  ChatState copyWith({
    List<ChatEntry>? messages,
    String? conversationId,
    String? vesselId,
    bool clearVessel = false,
    bool? sending,
    bool? loadingConversation,
    Object? error,
    bool clearError = false,
  }) =>
      ChatState(
        messages: messages ?? this.messages,
        conversationId: conversationId ?? this.conversationId,
        vesselId: clearVessel ? null : (vesselId ?? this.vesselId),
        sending: sending ?? this.sending,
        loadingConversation: loadingConversation ?? this.loadingConversation,
        error: clearError ? null : (error ?? this.error),
      );
}

/// The First Mate conversation, keyed by the vessel the chat was opened for
/// (`null` for `/chat`). Reset whenever the signed-in user changes.
final chatProvider = NotifierProvider.family<ChatController, ChatState, String?>(ChatController.new);

class ChatController extends Notifier<ChatState> {
  ChatController(this.routeVesselId);

  final String? routeVesselId;

  FirstMateApi get _api => ref.read(firstMateApiProvider);

  @override
  ChatState build() {
    ref.watch(currentUserIdProvider);
    return ChatState(vesselId: routeVesselId);
  }

  /// Sends [text]. Messages over [maxChatMessageChars] or blank are not sent.
  Future<void> send(String text) async {
    final message = text.trim();
    if (message.isEmpty || message.length > maxChatMessageChars || state.sending) return;
    if (state.conversationId == null && state.messages.isEmpty) {
      ref.read(monitoringProvider).capture('ai_conversation_started', properties: {
        'has_vessel_context': state.vesselId != null,
      });
    }
    final owner = ref.read(currentUserIdProvider);
    final entry = ChatEntry.user(message, DateTime.now());
    state = state.copyWith(messages: [...state.messages, entry], sending: true, clearError: true);
    try {
      final reply = await _api.chat(
        message: message,
        vesselId: state.vesselId,
        conversationId: state.conversationId,
      );
      if (!ref.mounted || ref.read(currentUserIdProvider) != owner) return;
      state = state.copyWith(
        messages: [...state.messages, ChatEntry.assistant(reply.turn)],
        conversationId: reply.conversationId,
        sending: false,
      );
      ref.invalidate(conversationListProvider);
    } catch (e) {
      if (!ref.mounted || ref.read(currentUserIdProvider) != owner) return;
      final messages = [...state.messages];
      final i = messages.lastIndexOf(entry);
      if (i >= 0) messages[i] = entry.markFailed();
      state = state.copyWith(messages: messages, sending: false, error: e);
    }
  }

  /// Re-sends the last failed message.
  Future<void> retry() async {
    final i = state.messages.lastIndexWhere((m) => m.failed);
    if (i < 0) return;
    final text = state.messages[i].content;
    state = state.copyWith(messages: [...state.messages]..removeAt(i), clearError: true);
    await send(text);
  }

  void dismissError() => state = state.copyWith(clearError: true);

  /// Chooses the vessel used for context from the next message on.
  void selectVessel(String? vesselId) =>
      state = vesselId == null ? state.copyWith(clearVessel: true) : state.copyWith(vesselId: vesselId);

  void newConversation() => state = ChatState(vesselId: state.vesselId);

  /// Re-opens a stored conversation (its vessel becomes the context).
  Future<void> open(String conversationId) async {
    state = state.copyWith(loadingConversation: true, clearError: true);
    try {
      final detail = await _api.conversation(conversationId);
      if (!ref.mounted) return;
      state = ChatState(
        conversationId: detail.summary.id,
        vesselId: detail.summary.vesselId ?? state.vesselId,
        messages: [
          for (final m in detail.messages)
            if (m.isUser) ChatEntry.user(m.content, m.createdAt) else ChatEntry.assistant(m.turn!),
        ],
      );
    } catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(loadingConversation: false, error: e);
    }
  }

  /// Deletes a stored conversation; the current one is cleared if it was it.
  Future<void> delete(String conversationId) async {
    await _api.deleteConversation(conversationId);
    if (!ref.mounted) return;
    if (state.conversationId == conversationId) newConversation();
    ref.invalidate(conversationListProvider);
  }
}

/// The user's stored conversations (most recent first).
final conversationListProvider = FutureProvider.autoDispose<List<ConversationSummary>>((ref) {
  requireUserId(ref);
  return ref.watch(firstMateApiProvider).conversations();
});
