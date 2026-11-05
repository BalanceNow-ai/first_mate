// ChatController against captured /ai/* payloads (provider level, no widgets).
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/ai_chat/providers/chat_provider.dart';

import '../../../helpers/fakes.dart';
import '../../content/engagement_test_helpers.dart';

Future<dynamic> signedIn(FakeBackend backend) async {
  final container = makeContainer(gateway: fixtureGateway(), backend: backend);
  addTearDown(container.dispose);
  container.read(authControllerProvider);
  await until(() => container.read(currentUserIdProvider) != null);
  return container;
}

void main() {
  test('send → reply carries the conversation id into the next turn', () async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_grounded'));
    final c = await signedIn(backend);
    final chat = c.read(chatProvider(null).notifier) as ChatController;
    await chat.send('  Which spark plug does my Yamaha F150 need?  ');
    ChatState s = c.read(chatProvider(null));
    expect(s.messages.map((m) => m.role), ['user', 'assistant']);
    expect(s.messages.first.content, 'Which spark plug does my Yamaha F150 need?');
    expect(s.lastTurn!.grounding!.status, GroundingStatus.grounded);
    expect(s.conversationId, engMap('ai_chat_grounded')['conversation_id']);

    backend.json('POST /ai/chat', 200, eng('ai_chat_followup'));
    await chat.send('And the oil filter?');
    expect((backend.calls('POST /ai/chat').last.body as Map)['conversation_id'], s.conversationId);
    s = c.read(chatProvider(null));
    expect(s.messages, hasLength(4));
  });

  test('blank and over-long messages are not sent', () async {
    final backend = engagementBackend();
    final c = await signedIn(backend);
    final chat = c.read(chatProvider(null).notifier) as ChatController;
    await chat.send('   ');
    await chat.send('x' * 2001);
    expect(backend.calls('POST /ai/chat'), isEmpty);
  });

  test('a failed send keeps the message as unsent; retry re-sends it once', () async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 422, eng('error_message_too_long'));
    final c = await signedIn(backend);
    final chat = c.read(chatProvider(null).notifier) as ChatController;
    await chat.send('Hello');
    var s = c.read(chatProvider(null)) as ChatState;
    expect(s.messages.single.failed, isTrue);
    expect(s.error, isNotNull);
    backend.json('POST /ai/chat', 200, eng('ai_chat_insufficient_evidence'));
    await chat.retry();
    s = c.read(chatProvider(null));
    expect(s.messages.map((m) => m.failed), [false, false]);
    expect(s.error, isNull);
    expect(backend.calls('POST /ai/chat'), hasLength(2));
  });

  test('open restores a stored conversation and its vessel; delete clears the current one', () async {
    final backend = engagementBackend();
    final detail = engMap('ai_conversation_detail');
    backend.json('GET /ai/conversations/${detail['id']}', 200, detail);
    backend.json('DELETE /ai/conversations/${detail['id']}', 204, null);
    final c = await signedIn(backend);
    final chat = c.read(chatProvider('route-vessel').notifier) as ChatController;
    expect(c.read(chatProvider('route-vessel')).vesselId, 'route-vessel');
    await chat.open(detail['id'] as String);
    var s = c.read(chatProvider('route-vessel')) as ChatState;
    expect(s.conversationId, detail['id']);
    expect(s.vesselId, detail['vessel_id']);
    expect(s.messages, hasLength(detail['message_count'] as int));
    await chat.delete(detail['id'] as String);
    s = c.read(chatProvider('route-vessel'));
    expect(s.isEmpty, isTrue);
    expect(s.conversationId, isNull);
  });
}
