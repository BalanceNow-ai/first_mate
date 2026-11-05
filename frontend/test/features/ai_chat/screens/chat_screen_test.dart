import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';
import 'package:helm_marine/features/ai_chat/providers/chat_provider.dart';
import 'package:helm_marine/features/ai_chat/screens/chat_screen.dart';

import '../../../helpers/fakes.dart';

void main() {
  group('ChatScreen', () {
    testWidgets('shows empty state with First Mate AI title', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: baseTestOverrides(),
          child: const MaterialApp(home: ChatScreen()),
        ),
      );
      await tester.pump();

      expect(find.text('First Mate AI'), findsWidgets);
    });

    testWidgets('shows suggestion chips in empty state', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: baseTestOverrides(),
          child: const MaterialApp(home: ChatScreen()),
        ),
      );
      await tester.pump();

      expect(find.text('What oil does my engine need?'), findsOneWidget);
      expect(find.text('Pre-season checklist'), findsOneWidget);
      expect(find.text('Recommended safety gear'), findsOneWidget);
    });

    testWidgets('shows vessel chat title when vesselId provided',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: baseTestOverrides(),
          child: const MaterialApp(home: ChatScreen(vesselId: 'test-vessel')),
        ),
      );
      await tester.pump();

      expect(find.text('First Mate - Vessel Chat'), findsOneWidget);
    });

    testWidgets('has message input field', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: baseTestOverrides(),
          child: const MaterialApp(home: ChatScreen()),
        ),
      );
      await tester.pump();

      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Ask your First Mate...'), findsOneWidget);
    });

    testWidgets('user messages are plain text, not markdown', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            ...baseTestOverrides(),
            chatProvider(null).overrideWith((ref) {
              final notifier = ChatNotifier(
                ApiService(Dio()),
                const Monitoring.disabled(),
              );
              notifier.state = ChatState(
                messages: [
                  ChatMessage(role: 'user', content: '**bold text**'),
                ],
              );
              return notifier;
            }),
          ],
          child: const MaterialApp(home: ChatScreen()),
        ),
      );
      await tester.pump();

      // User messages should use Text widget, not MarkdownBody
      expect(find.text('**bold text**'), findsOneWidget);
      expect(find.byType(MarkdownBody), findsNothing);
    });

    testWidgets('assistant messages use markdown rendering', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            ...baseTestOverrides(),
            chatProvider(null).overrideWith((ref) {
              final notifier = ChatNotifier(
                ApiService(Dio()),
                const Monitoring.disabled(),
              );
              notifier.state = ChatState(
                messages: [
                  ChatMessage(
                    role: 'assistant',
                    content: '**Bold** and *italic*',
                  ),
                ],
              );
              return notifier;
            }),
          ],
          child: const MaterialApp(home: ChatScreen()),
        ),
      );
      await tester.pump();

      expect(find.byType(MarkdownBody), findsOneWidget);
    });
  });
}
