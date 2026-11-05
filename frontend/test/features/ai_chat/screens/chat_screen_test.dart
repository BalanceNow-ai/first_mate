// First Mate chat in the real app shell, fed with captured server payloads.
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fakes.dart';
import '../../content/engagement_test_helpers.dart';

Future<void> ask(dynamic app, WidgetTester tester, String text) async {
  await tester.enterText(find.widgetWithText(TextField, 'Ask your First Mate'), text);
  await tester.pump();
  await app.tap(find.byTooltip('Send'));
}

void main() {
  testWidgets('grounded answer: banner, markdown, sources, local badge, fitting product, action', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_grounded'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();

    await ask(app, tester, 'Which spark plug does my Yamaha F150 need?');

    final body = backend.calls('POST /ai/chat').single.body as Map;
    expect(body['message'], 'Which spark plug does my Yamaha F150 need?');
    expect(body.containsKey('conversation_id'), isFalse);
    expect(find.text('Which spark plug does my Yamaha F150 need?'), findsOneWidget);
    expect(find.text('Grounded in admitted sources'), findsOneWidget);
    expect(find.text('Local test assistant'), findsOneWidget);
    expect(find.byType(MarkdownBody), findsOneWidget);
    expect(find.text('Sources'), findsOneWidget);
    expect(find.text('Synthetic service notes — Yamaha F150 outboard'), findsOneWidget);
    expect(find.text('Synthetic test source'), findsOneWidget);
    expect(find.text('Fits Kahawai'), findsOneWidget);
    expect(find.text('Add to cart'), findsOneWidget);
    // Nothing is added to the cart until the user taps the action.
    expect(backend.calls('POST /cart/items'), isEmpty);
  });

  testWidgets('tapping Add to cart posts the action to the normal cart API; errors are shown', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_grounded'));
    backend.json('POST /cart/items', 409, fixture('error_insufficient_stock'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();
    await ask(app, tester, 'Which spark plug does my Yamaha F150 need?');

    await app.tap(find.text('Add to cart'));
    final action = (engMap('ai_chat_grounded')['actions'] as List).single as Map;
    final add = backend.calls('POST /cart/items').single.body as Map;
    expect(add, {'product_id': action['product_id'], 'quantity': action['quantity']});
    final detail = fixtureMap('error_insufficient_stock')['detail'] as String;
    expect(find.textContaining(detail), findsWidgets);

    backend.json('POST /cart/items', 201, fixture('cart_with_item'));
    await app.tap(find.text('Add to cart'));
    expect(backend.calls('POST /cart/items'), hasLength(2));
    expect(find.text('Added to cart'), findsWidgets);
  });

  testWidgets('insufficient evidence and conflicting answers show their banners and no actions', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_insufficient_evidence'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();
    await ask(app, tester, 'What colour should I paint my anchor locker?');
    expect(find.text('No verified source — the First Mate asked a clarifying question'), findsOneWidget);
    expect(find.text('Sources'), findsNothing);
    expect(find.text('Add to cart'), findsNothing);

    backend.json('POST /ai/chat', 200, eng('ai_chat_conflicting'));
    await ask(app, tester, 'Which spark plug does my Helmsynth HX90 need?');
    // The follow-up continues the same conversation.
    final second = backend.calls('POST /ai/chat').last.body as Map;
    expect(second['conversation_id'], engMap('ai_chat_insufficient_evidence')['conversation_id']);
    expect(find.text('Sources disagree'), findsOneWidget);
    expect(find.text('Add to cart'), findsNothing);
    // Mismatched parts are labelled as not fitting, never as fitting.
    expect(find.text('Does not fit', skipOffstage: false), findsWidgets);
  });

  testWidgets('429 and 503 states, and the failed message can be retried', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 429, eng('error_rate_limited'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();
    await ask(app, tester, 'Hi');
    expect(find.text('Slow down a little'), findsOneWidget);
    expect(find.text('Not sent'), findsOneWidget);
    expect(find.text('Code: rate_limited'), findsOneWidget);

    // 503 ai_unavailable is configuration-dependent and was not captured from
    // the running stack (AI is enabled there); the server's error shape is
    // `{detail, code}` exactly as for every captured error.
    backend.on('POST /ai/chat', (_) => const FakeResponse(503, {
          'detail': 'First Mate is not available right now',
          'code': 'ai_unavailable',
        }));
    await app.tap(find.byIcon(Icons.close));
    await ask(app, tester, 'Hello again');
    expect(find.text('First Mate is unavailable'), findsOneWidget);

    backend.json('POST /ai/chat', 200, eng('ai_chat_insufficient_evidence'));
    await app.tap(find.text('Retry'));
    expect(find.text('Not sent'), findsOneWidget, reason: 'only the first (rate-limited) message remains unsent');
    expect(find.text('No verified source — the First Mate asked a clarifying question'), findsOneWidget);
  });

  testWidgets('message length counter and limit; suggestion chips send', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_grounded'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();
    expect(find.text('0 / 2000'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Ask your First Mate'), 'x' * 2500);
    await tester.pump();
    expect(find.text('2000 / 2000'), findsOneWidget, reason: 'input is capped at the server limit');

    await tester.enterText(find.widgetWithText(TextField, 'Ask your First Mate'), '');
    await app.tap(find.text('Which spark plug does my engine need?'));
    expect((backend.calls('POST /ai/chat').single.body as Map)['message'], 'Which spark plug does my engine need?');
  });

  testWidgets('vessel switcher offers only the user\'s vessels and sends vessel_id', (tester) async {
    final backend = engagementBackend();
    backend.json('POST /ai/chat', 200, eng('ai_chat_grounded'));
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();
    expect(find.textContaining('Vessel: Sea Biscuit'), findsOneWidget);
    await app.tap(find.textContaining('Vessel: Sea Biscuit'));
    expect(find.text('Ask about which vessel?'), findsOneWidget);
    expect(find.text('Tender'), findsOneWidget);
    await app.tap(find.text('Tender'));
    expect(find.textContaining('Vessel: Tender'), findsOneWidget);
    await ask(app, tester, 'Pre-season checklist');
    final tender = (fixture('vessels_list') as List).cast<Map>().firstWhere((v) => v['nickname'] == 'Tender');
    expect((backend.calls('POST /ai/chat').single.body as Map)['vessel_id'], tender['id']);
  });

  testWidgets('conversation list: reopen a stored conversation and delete one', (tester) async {
    final backend = engagementBackend();
    final detail = engMap('ai_conversation_detail');
    backend.json('GET /ai/conversations/${detail['id']}', 200, detail);
    final conversations = engList('ai_conversations');
    final victim = conversations.first;
    backend.json('DELETE /ai/conversations/${victim['id']}', 204, null);
    final app = await engagementApp(tester, backend: backend);
    app.go('/chat');
    await app.settle();

    await app.tap(find.byTooltip('Conversations'));
    expect(find.text('Conversations'), findsOneWidget);
    for (final c in conversations) {
      expect(find.text(c['title'] as String), findsOneWidget);
    }
    await app.tap(find.text(detail['title'] as String));
    expect(backend.calls('GET /ai/conversations/${detail['id']}'), hasLength(1));
    expect(find.text('Grounded in admitted sources'), findsNWidgets(2));
    expect(find.text('Add to cart'), findsNWidgets(2));

    await app.tap(find.byTooltip('Conversations'));
    await app.tap(find.byTooltip('Delete conversation').first);
    await app.tap(find.widgetWithText(FilledButton, 'Delete'));
    expect(backend.calls('DELETE /ai/conversations/${victim['id']}'), hasLength(1));
  });
}
