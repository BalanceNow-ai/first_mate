import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/ai_chat/providers/chat_provider.dart';

void main() {
  group('ChatMessage', () {
    test('creates user message', () {
      final msg = ChatMessage(role: 'user', content: 'Hello');

      expect(msg.role, 'user');
      expect(msg.content, 'Hello');
      expect(msg.timestamp, isNotNull);
    });

    test('creates assistant message', () {
      final msg = ChatMessage(role: 'assistant', content: 'Hi there!');

      expect(msg.role, 'assistant');
      expect(msg.content, 'Hi there!');
    });
  });

  group('ChatState', () {
    test('default state has empty messages', () {
      const state = ChatState();

      expect(state.messages, isEmpty);
      expect(state.conversationId, isNull);
      expect(state.isLoading, false);
      expect(state.error, isNull);
    });

    test('copyWith preserves unchanged fields', () {
      const state = ChatState(isLoading: true);
      final updated = state.copyWith(error: 'Network error');

      expect(updated.isLoading, true); // preserved
      expect(updated.error, 'Network error'); // changed
    });

    test('copyWith can add messages', () {
      const state = ChatState();
      final msg = ChatMessage(role: 'user', content: 'Test');
      final updated = state.copyWith(messages: [msg]);

      expect(updated.messages.length, 1);
      expect(updated.messages.first.content, 'Test');
    });
  });

}
