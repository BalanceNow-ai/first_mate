// Contract: First Mate models parse REAL /ai/* payloads captured from the local stack.
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/features/ai_chat/widgets/answer_widgets.dart';

import '../content/engagement_test_helpers.dart';

void main() {
  test('grounded answer: citations, verified-fit product, explicit cart action, local mode', () {
    final reply = ChatReply.fromJson(engMap('ai_chat_grounded'));
    final t = reply.turn;
    expect(reply.conversationId, isNotEmpty);
    expect(t.grounding!.status, GroundingStatus.grounded);
    expect(t.grounding!.specialistsConsulted, contains('engine'));
    expect(t.citations, isNotEmpty);
    final c = t.citations.first;
    expect(c.index, 1);
    expect(c.isSynthetic, isTrue);
    expect(c.licence, isNotEmpty);
    expect(c.url, isNull);
    expect(t.content, contains('[1]'));
    final plug = t.products.singleWhere((p) => p.sku == 'SYN-PLUG-150');
    expect(plug.fitment.status, FitmentStatus.verifiedFit);
    expect(plug.effectivePriceCents, 8990);
    expect(plug.priceText, r'$89.90');
    expect(t.actions.single.productId, plug.id);
    expect(t.actions.single.type, 'add_to_cart');
    expect(t.actions.single.quantity, 1);
    expect(t.vessel!.label, startsWith('Kahawai'));
    expect(t.isLocalTestAssistant, isTrue);
  });

  test('insufficient evidence: no citations, products or actions', () {
    final t = ChatReply.fromJson(engMap('ai_chat_insufficient_evidence')).turn;
    expect(t.grounding!.status, GroundingStatus.insufficientEvidence);
    expect(t.citations, isEmpty);
    expect(t.actions, isEmpty);
    expect(t.content, contains('Could you'));
  });

  test('conflicting: two cited sources, no actions, mismatches never shown as fitting', () {
    final t = ChatReply.fromJson(engMap('ai_chat_conflicting')).turn;
    expect(t.grounding!.status, GroundingStatus.conflicting);
    expect(t.citations.map((c) => c.index), [1, 2]);
    expect(t.actions, isEmpty);
    final f150 = t.products.singleWhere((p) => p.sku == 'SYN-PLUG-150');
    expect(f150.fitment.status, FitmentStatus.verifiedMismatch);
    expect(f150.fitment.status.fits, isFalse);
  });

  test('follow-up turn keeps the conversation id', () {
    final first = ChatReply.fromJson(engMap('ai_chat_grounded'));
    final next = ChatReply.fromJson(engMap('ai_chat_followup'));
    expect(next.conversationId, first.conversationId);
  });

  test('conversation list and detail (stored assistant turns keep grounding and actions)', () {
    final list = [for (final c in engList('ai_conversations')) ConversationSummary.fromJson(c)];
    expect(list, isNotEmpty);
    expect(list.every((c) => c.messageCount >= 2), isTrue);
    final detail = ConversationDetail.fromJson(engMap('ai_conversation_detail'));
    expect(detail.messages.length, detail.summary.messageCount);
    expect(detail.messages.first.isUser, isTrue);
    expect(detail.messages.first.turn, isNull);
    final answer = detail.messages[1].turn!;
    expect(answer.grounding!.status, GroundingStatus.grounded);
    expect(answer.actions, isNotEmpty);
    expect(answer.mode, 'local_extractive');
  });

  test('specialists list', () {
    final s = [for (final j in engList('ai_specialists')) SpecialistInfo.fromJson(j)];
    expect(s.map((x) => x.key), containsAll(['engine', 'anchoring', 'safety']));
  });

  test('error payloads: message_too_long, rate_limited, not_found', () {
    final tooLong = ApiError.fromResponse(422, engMap('error_message_too_long'));
    expect(tooLong.code, 'message_too_long');
    expect(tooLong.detail, contains('2000'));
    final limited = ApiError.fromResponse(429, engMap('error_rate_limited'));
    expect(limited.code, 'rate_limited');
    final missing = ApiError.fromResponse(404, engMap('error_conversation_not_found'));
    expect(missing.isNotFound, isTrue);
  });

  test('citation markers become links only for real citations', () {
    expect(answerMarkdown('Gap is 0.9 mm [1] and [7].', {1}), r'Gap is 0.9 mm [\[1\]](cite:1) and \[7\].');
    final md = answerMarkdown(engMap('ai_chat_grounded')['message']['content'] as String, {1});
    expect(md, contains('(cite:1)'));
    expect(RegExp(r'[^\n]\n\*\*').hasMatch(md), isFalse, reason: 'headings are separated from lists by a blank line');
  });
}
