import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/checklist.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/checklists/data/checklist_api.dart';
import 'package:helm_marine/features/checklists/export/export_saver.dart';

/// A vessel's checklist set (all tiers). Mutations replace items with the
/// server's response; ticking is optimistic and rolled back on failure.
final checklistSetProvider =
    AsyncNotifierProvider.autoDispose.family<ChecklistNotifier, ChecklistSet, String>(ChecklistNotifier.new);

class ChecklistNotifier extends AsyncNotifier<ChecklistSet> {
  ChecklistNotifier(this.vesselId);

  final String vesselId;

  ChecklistApi get _api => ref.read(checklistApiProvider);

  @override
  Future<ChecklistSet> build() {
    final api = ref.watch(checklistApiProvider);
    requireUserId(ref);
    return api.get(vesselId);
  }

  /// Generates the tiers (or rebuilds them, keeping ticks by template key).
  Future<void> generate({bool regenerate = false}) async {
    final set = await _api.generate(vesselId, regenerate: regenerate);
    if (ref.mounted) state = AsyncData(set);
  }

  /// Deletes every tier for the vessel.
  Future<void> deleteAll() async {
    await _api.deleteAll(vesselId);
    if (ref.mounted) state = AsyncData(await _api.get(vesselId));
  }

  /// Optimistically ticks/unticks [itemId] everywhere it appears; rolls back
  /// and rethrows when the server refuses.
  Future<void> setChecked(String itemId, bool checked) async {
    final before = state.value;
    if (before == null) return;
    state = AsyncData(before.updateItem(itemId, (i) => i.copyWith(isChecked: checked)));
    try {
      final item = await _api.setChecked(itemId, checked);
      final current = state.value;
      if (ref.mounted && current != null) state = AsyncData(current.replaceItem(item));
    } catch (_) {
      final current = state.value;
      if (ref.mounted && current != null) {
        // Restore only this item's previous state; other changes stay.
        final previous = _find(before, itemId);
        state = AsyncData(previous == null ? before : current.replaceItem(previous));
      }
      rethrow;
    }
  }

  static ChecklistItem? _find(ChecklistSet set, String itemId) {
    for (final t in set.tiers) {
      for (final i in t.items) {
        if (i.id == itemId) return i;
      }
    }
    return null;
  }

  /// Links an owner-chosen product. Throws `ApiError` (`fitment_mismatch`)
  /// for a verified mismatch; returns the item (with any `warning`).
  Future<ChecklistItem> link(String itemId, String productId) async {
    final item = await _api.link(itemId, productId);
    final current = state.value;
    if (ref.mounted && current != null) state = AsyncData(current.replaceItem(item));
    return item;
  }

  /// Adds the tier's unchecked linked items to the cart (idempotent) and
  /// refreshes the cart badge.
  Future<AddMissingResult> addMissingToCart(ChecklistTierId tier) async {
    final result = await _api.addMissingToCart(vesselId, tier);
    ref.invalidate(cartProvider);
    return result;
  }
}

/// Opens/saves exports; overridden in tests.
final exportDelivererProvider = Provider<ExportDeliverer>((ref) => const ExportDeliverer());

class ExportDeliverer {
  const ExportDeliverer();

  /// Must be called synchronously from the user's tap (see [ExportTarget]).
  ExportTarget open(ExportFormat format) => ExportTarget.open(format);

  Future<String> deliver(ChecklistExport export, ExportTarget target) => deliverExport(export, target);
}
