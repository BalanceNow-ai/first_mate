/// Voyage spares checklist contracts (`/checklists/...`).
library;

import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/models/product.dart';

/// The three cumulative tiers, in order.
enum ChecklistTierId {
  grabAndGo('grab_and_go', 'Day trips'),
  coastalCruising('coastal_cruising', 'Coastal'),
  offshorePassage('offshore_passage', 'Offshore');

  const ChecklistTierId(this.wire, this.shortName);

  final String wire;

  /// Tab label.
  final String shortName;

  static ChecklistTierId parse(String value) => ChecklistTierId.values.firstWhere(
        (t) => t.wire == value,
        orElse: () => throw FormatException('Unknown checklist tier "$value"'),
      );
}

/// Where an item's product link came from (`link_status`).
enum LinkStatus {
  verifiedFit('verified_fit'),
  universal('universal'),

  /// The owner chose a product whose fit is not verified.
  userLinkedUnverified('user_linked_unverified'),
  unlinked('unlinked');

  const LinkStatus(this.wire);

  final String wire;

  static LinkStatus parse(String value) =>
      LinkStatus.values.firstWhere((s) => s.wire == value, orElse: () => LinkStatus.unlinked);
}

/// `SearchHint` — how to find a compatible product for an unlinked item.
class SearchHint {
  const SearchHint({required this.q, required this.vesselId, required this.path, this.partRole});

  final String q;
  final String? partRole;
  final String vesselId;
  final String path;

  factory SearchHint.fromJson(Map<String, dynamic> json) => SearchHint(
        q: req<String>(json, 'q'),
        partRole: opt<String>(json, 'part_role'),
        vesselId: req<String>(json, 'vessel_id'),
        path: req<String>(json, 'path'),
      );
}

/// `ChecklistItemResponse`.
class ChecklistItem {
  const ChecklistItem({
    required this.id,
    required this.introducedIn,
    required this.position,
    required this.system,
    required this.itemName,
    required this.quantity,
    required this.applicability,
    required this.isChecked,
    required this.linkStatus,
    this.templateKey,
    this.description,
    this.partRole,
    this.checkedAt,
    this.product,
    this.fitment,
    this.alternatives = const [],
    this.searchHint,
    this.warning,
  });

  final String id;
  final String? templateKey;
  final ChecklistTierId introducedIn;
  final int position;
  final String system;
  final String itemName;
  final String? description;
  final int quantity;
  final String? partRole;

  /// `applies` | `if_fitted`.
  final String applicability;
  final bool isChecked;
  final DateTime? checkedAt;
  final LinkStatus linkStatus;
  final Product? product;
  final Fitment? fitment;
  final List<Product> alternatives;
  final SearchHint? searchHint;
  final String? warning;

  bool get ifFitted => applicability == 'if_fitted';

  ChecklistItem copyWith({bool? isChecked}) => ChecklistItem(
        id: id,
        templateKey: templateKey,
        introducedIn: introducedIn,
        position: position,
        system: system,
        itemName: itemName,
        description: description,
        quantity: quantity,
        partRole: partRole,
        applicability: applicability,
        isChecked: isChecked ?? this.isChecked,
        checkedAt: checkedAt,
        linkStatus: linkStatus,
        product: product,
        fitment: fitment,
        alternatives: alternatives,
        searchHint: searchHint,
        warning: warning,
      );

  factory ChecklistItem.fromJson(Map<String, dynamic> json) {
    final product = optMap(json, 'product');
    final fitment = optMap(json, 'fitment');
    final hint = optMap(json, 'search_hint');
    final checkedAt = opt<String>(json, 'checked_at');
    return ChecklistItem(
      id: req<String>(json, 'id'),
      templateKey: opt<String>(json, 'template_key'),
      introducedIn: ChecklistTierId.parse(req<String>(json, 'introduced_in')),
      position: req<int>(json, 'position'),
      system: req<String>(json, 'system'),
      itemName: req<String>(json, 'item_name'),
      description: opt<String>(json, 'description'),
      quantity: req<int>(json, 'quantity'),
      partRole: opt<String>(json, 'part_role'),
      applicability: req<String>(json, 'applicability'),
      isChecked: req<bool>(json, 'is_checked'),
      checkedAt: checkedAt == null ? null : DateTime.parse(checkedAt),
      linkStatus: LinkStatus.parse(req<String>(json, 'link_status')),
      product: product == null ? null : Product.fromJson(product),
      fitment: fitment == null ? null : Fitment.fromJson(fitment),
      alternatives: [for (final p in mapList(json, 'alternatives')) Product.fromJson(p)],
      searchHint: hint == null ? null : SearchHint.fromJson(hint),
      warning: opt<String>(json, 'warning'),
    );
  }
}

/// `TierResponse` — a tier's cumulative items (earlier tiers' items included,
/// marked by [ChecklistItem.introducedIn]).
class ChecklistTier {
  const ChecklistTier({
    required this.tier,
    required this.name,
    required this.checklistId,
    required this.items,
    required this.total,
    required this.checked,
    required this.uncheckedLinked,
  });

  final ChecklistTierId tier;
  final String name;
  final String checklistId;
  final List<ChecklistItem> items;
  final int total;
  final int checked;
  final int uncheckedLinked;

  /// Replaces items by id, recomputing the counts the server derives from them.
  ChecklistTier withItems(ChecklistItem Function(ChecklistItem) update) {
    final next = [for (final i in items) update(i)];
    return ChecklistTier(
      tier: tier,
      name: name,
      checklistId: checklistId,
      items: next,
      total: next.length,
      checked: next.where((i) => i.isChecked).length,
      uncheckedLinked: next.where((i) => !i.isChecked && i.product != null).length,
    );
  }

  factory ChecklistTier.fromJson(Map<String, dynamic> json) => ChecklistTier(
        tier: ChecklistTierId.parse(req<String>(json, 'tier')),
        name: req<String>(json, 'name'),
        checklistId: req<String>(json, 'checklist_id'),
        items: [for (final i in mapList(json, 'items')) ChecklistItem.fromJson(i)],
        total: req<int>(json, 'total'),
        checked: req<int>(json, 'checked'),
        uncheckedLinked: req<int>(json, 'unchecked_linked'),
      );
}

/// `ChecklistSetResponse`.
class ChecklistSet {
  const ChecklistSet({
    required this.vessel,
    required this.generated,
    required this.disclaimer,
    required this.tiers,
    this.templateVersion,
  });

  final VesselRef vessel;
  final bool generated;
  final String? templateVersion;

  /// Always shown: a practical spares list, not a compliance assessment.
  final String disclaimer;
  final List<ChecklistTier> tiers;

  ChecklistTier? tier(ChecklistTierId id) {
    for (final t in tiers) {
      if (t.tier == id) return t;
    }
    return null;
  }

  /// Applies [update] to every occurrence of item [itemId] (items are shared
  /// by every tier that includes them).
  ChecklistSet updateItem(String itemId, ChecklistItem Function(ChecklistItem) update) => ChecklistSet(
        vessel: vessel,
        generated: generated,
        templateVersion: templateVersion,
        disclaimer: disclaimer,
        tiers: [for (final t in tiers) t.withItems((i) => i.id == itemId ? update(i) : i)],
      );

  /// Replaces item [item] everywhere, keeping each tier's `introduced_in` view.
  ChecklistSet replaceItem(ChecklistItem item) => updateItem(item.id, (_) => item);

  factory ChecklistSet.fromJson(Map<String, dynamic> json) => ChecklistSet(
        vessel: VesselRef.fromJson(reqMap(json, 'vessel')),
        generated: req<bool>(json, 'generated'),
        templateVersion: opt<String>(json, 'template_version'),
        disclaimer: req<String>(json, 'disclaimer'),
        tiers: [for (final t in mapList(json, 'tiers')) ChecklistTier.fromJson(t)],
      );
}

/// One line of "add missing to cart" (`AddMissingLine`).
class AddMissingLine {
  const AddMissingLine({
    required this.itemId,
    required this.itemName,
    required this.productId,
    required this.requested,
    required this.added,
    required this.quantityInCart,
    required this.status,
    this.templateKey,
    this.message,
  });

  final String itemId;
  final String? templateKey;
  final String itemName;
  final String productId;
  final int requested;
  final int added;
  final int quantityInCart;

  /// `added` | `already_satisfied` | `limited` | `insufficient_stock` | `unavailable`.
  final String status;
  final String? message;

  /// Short label for [status].
  String get statusLabel => switch (status) {
        'added' => 'Added',
        'already_satisfied' => 'Already in cart',
        'limited' => 'Limited stock',
        'insufficient_stock' => 'Not enough stock',
        'unavailable' => 'Unavailable',
        _ => status.replaceAll('_', ' '),
      };

  factory AddMissingLine.fromJson(Map<String, dynamic> json) => AddMissingLine(
        itemId: req<String>(json, 'item_id'),
        templateKey: opt<String>(json, 'template_key'),
        itemName: req<String>(json, 'item_name'),
        productId: req<String>(json, 'product_id'),
        requested: req<int>(json, 'requested'),
        added: req<int>(json, 'added'),
        quantityInCart: req<int>(json, 'quantity_in_cart'),
        status: req<String>(json, 'status'),
        message: opt<String>(json, 'message'),
      );
}

/// An unchecked item that could not be added (`SkippedItem`).
class SkippedChecklistItem {
  const SkippedChecklistItem({required this.itemId, required this.itemName, required this.reason});

  final String itemId;
  final String itemName;
  final String reason;

  factory SkippedChecklistItem.fromJson(Map<String, dynamic> json) => SkippedChecklistItem(
        itemId: req<String>(json, 'item_id'),
        itemName: req<String>(json, 'item_name'),
        reason: req<String>(json, 'reason'),
      );
}

/// `AddMissingResponse`.
class AddMissingResult {
  const AddMissingResult({
    required this.tier,
    required this.addedCount,
    required this.lines,
    this.skipped = const [],
  });

  final ChecklistTierId tier;
  final int addedCount;
  final List<AddMissingLine> lines;
  final List<SkippedChecklistItem> skipped;

  factory AddMissingResult.fromJson(Map<String, dynamic> json) => AddMissingResult(
        tier: ChecklistTierId.parse(req<String>(json, 'tier')),
        addedCount: req<int>(json, 'added_count'),
        lines: [for (final l in mapList(json, 'lines')) AddMissingLine.fromJson(l)],
        skipped: [
          for (final s in (json['skipped'] as List? ?? const []))
            SkippedChecklistItem.fromJson((s as Map).cast<String, dynamic>()),
        ],
      );
}
