import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/money/money.dart';

/// How well an answer is supported by admitted knowledge (`Grounding.status`).
enum GroundingStatus {
  grounded('grounded'),
  insufficientEvidence('insufficient_evidence'),
  conflicting('conflicting');

  const GroundingStatus(this.wire);

  final String wire;

  /// Unrecognised values are treated as [insufficientEvidence] — never as grounded.
  static GroundingStatus parse(String? value) => GroundingStatus.values.firstWhere(
        (s) => s.wire == value,
        orElse: () => GroundingStatus.insufficientEvidence,
      );
}

/// `Grounding`: status, the specialist domains consulted and a server note.
class Grounding {
  const Grounding({required this.status, required this.specialistsConsulted, required this.note});

  final GroundingStatus status;
  final List<String> specialistsConsulted;
  final String note;

  factory Grounding.fromJson(Map<String, dynamic> json) => Grounding(
        status: GroundingStatus.parse(req<String>(json, 'status')),
        specialistsConsulted: stringList(json, 'specialists_consulted'),
        note: req<String>(json, 'note'),
      );
}

/// A cited source passage (`Citation`); `[index]` markers in the answer refer to it.
class Citation {
  const Citation({
    required this.index,
    required this.sourceId,
    required this.chunkId,
    required this.title,
    required this.licence,
    required this.excerpt,
    required this.isSynthetic,
    this.publisher,
    this.url,
  });

  final int index;
  final String sourceId;
  final String chunkId;
  final String title;
  final String? publisher;
  final String? url;
  final String licence;
  final String excerpt;
  final bool isSynthetic;

  factory Citation.fromJson(Map<String, dynamic> json) => Citation(
        index: req<int>(json, 'index'),
        sourceId: req<String>(json, 'source_id'),
        chunkId: req<String>(json, 'chunk_id'),
        title: req<String>(json, 'title'),
        publisher: opt<String>(json, 'publisher'),
        url: opt<String>(json, 'url'),
        licence: req<String>(json, 'licence'),
        excerpt: req<String>(json, 'excerpt'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
      );
}

/// A product the First Mate referenced, with the central fitment result
/// (`ProductReference`).
class ProductReference {
  const ProductReference({
    required this.id,
    required this.name,
    required this.sku,
    required this.effectivePriceCents,
    required this.currency,
    required this.inStock,
    required this.fitment,
    this.brand,
    this.image,
  });

  final String id;
  final String name;
  final String sku;
  final String? brand;
  final int effectivePriceCents;
  final String currency;
  final bool inStock;
  final String? image;
  final Fitment fitment;

  String get priceText => formatCents(effectivePriceCents, currency: currency);

  factory ProductReference.fromJson(Map<String, dynamic> json) => ProductReference(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        sku: req<String>(json, 'sku'),
        brand: opt<String>(json, 'brand'),
        effectivePriceCents: centsFrom(json, 'effective_price_cents'),
        currency: req<String>(json, 'currency'),
        inStock: req<bool>(json, 'in_stock'),
        image: opt<String>(json, 'image'),
        fitment: Fitment.fromJson(reqMap(json, 'fitment')),
      );
}

/// A proposed cart addition (`CartAction`). Nothing is added until the user taps
/// it; the client then calls the normal `POST /cart/items`.
class CartAction {
  const CartAction({
    required this.type,
    required this.productId,
    required this.quantity,
    required this.label,
  });

  final String type;
  final String productId;
  final int quantity;
  final String label;

  factory CartAction.fromJson(Map<String, dynamic> json) => CartAction(
        type: req<String>(json, 'type'),
        productId: req<String>(json, 'product_id'),
        quantity: req<int>(json, 'quantity'),
        label: req<String>(json, 'label'),
      );
}

/// Shared shape of a chat response and a stored assistant message.
class AssistantTurn {
  const AssistantTurn({
    required this.content,
    required this.createdAt,
    this.grounding,
    this.citations = const [],
    this.products = const [],
    this.actions = const [],
    this.vessel,
    this.mode,
  });

  final String content;
  final DateTime createdAt;
  final Grounding? grounding;
  final List<Citation> citations;
  final List<ProductReference> products;
  final List<CartAction> actions;
  final VesselRef? vessel;

  /// `openai` or `local_extractive` (the local, deterministic test assistant).
  final String? mode;

  bool get isLocalTestAssistant => mode == 'local_extractive';

  static AssistantTurn _parse(Map<String, dynamic> json, Map<String, dynamic> message) {
    final grounding = optMap(json, 'grounding');
    final vessel = optMap(json, 'vessel');
    return AssistantTurn(
      content: req<String>(message, 'content'),
      createdAt: reqDate(message, 'created_at'),
      grounding: grounding == null ? null : Grounding.fromJson(grounding),
      citations: [for (final c in _list(json, 'citations')) Citation.fromJson(c)],
      products: [for (final p in _list(json, 'products')) ProductReference.fromJson(p)],
      actions: [for (final a in _list(json, 'actions')) CartAction.fromJson(a)],
      vessel: vessel == null ? null : VesselRef.fromJson(vessel),
      mode: opt<String>(json, 'mode'),
    );
  }

  static List<Map<String, dynamic>> _list(Map<String, dynamic> json, String key) =>
      json[key] == null ? const [] : mapList(json, key);
}

/// `POST /ai/chat` response (`ChatResponse`).
class ChatReply {
  const ChatReply({required this.conversationId, required this.turn});

  final String conversationId;
  final AssistantTurn turn;

  factory ChatReply.fromJson(Map<String, dynamic> json) {
    final turn = AssistantTurn._parse(json, reqMap(json, 'message'));
    if (turn.grounding == null) throw const FormatException('Field "grounding": missing object');
    req<String>(json, 'mode');
    return ChatReply(conversationId: req<String>(json, 'conversation_id'), turn: turn);
  }
}

/// A message stored in a conversation (`StoredMessage`).
class StoredMessage {
  const StoredMessage({required this.role, required this.content, required this.createdAt, this.turn});

  /// `user` or `assistant`.
  final String role;
  final String content;
  final DateTime createdAt;

  /// The assistant's grounding, citations, products and actions (assistant only).
  final AssistantTurn? turn;

  bool get isUser => role == 'user';

  factory StoredMessage.fromJson(Map<String, dynamic> json) {
    final role = req<String>(json, 'role');
    return StoredMessage(
      role: role,
      content: req<String>(json, 'content'),
      createdAt: reqDate(json, 'created_at'),
      turn: role == 'assistant' ? AssistantTurn._parse(json, json) : null,
    );
  }
}

/// `ConversationSummary` from `GET /ai/conversations`.
class ConversationSummary {
  const ConversationSummary({
    required this.id,
    required this.messageCount,
    required this.createdAt,
    required this.updatedAt,
    this.title,
    this.vesselId,
  });

  final String id;
  final String? title;
  final String? vesselId;
  final int messageCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  String get displayTitle => (title == null || title!.trim().isEmpty) ? 'Conversation' : title!;

  factory ConversationSummary.fromJson(Map<String, dynamic> json) => ConversationSummary(
        id: req<String>(json, 'id'),
        title: opt<String>(json, 'title'),
        vesselId: opt<String>(json, 'vessel_id'),
        messageCount: req<int>(json, 'message_count'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

/// `ConversationDetail` from `GET /ai/conversations/{id}`.
class ConversationDetail {
  const ConversationDetail({required this.summary, required this.messages});

  final ConversationSummary summary;
  final List<StoredMessage> messages;

  factory ConversationDetail.fromJson(Map<String, dynamic> json) => ConversationDetail(
        summary: ConversationSummary.fromJson(json),
        messages: [for (final m in mapList(json, 'messages')) StoredMessage.fromJson(m)],
      );
}

/// `SpecialistInfo` from `GET /ai/specialists` (also the knowledge domains).
class SpecialistInfo {
  const SpecialistInfo({required this.key, required this.name, required this.description});

  final String key;
  final String name;
  final String description;

  factory SpecialistInfo.fromJson(Map<String, dynamic> json) => SpecialistInfo(
        key: req<String>(json, 'key'),
        name: req<String>(json, 'name'),
        description: req<String>(json, 'description'),
      );
}
