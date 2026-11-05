import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/session/session.dart';

/// The signed-in user's vessels (primary first, as ordered by the server).
final vesselListProvider =
    AsyncNotifierProvider<VesselListNotifier, List<Vessel>>(VesselListNotifier.new);

class VesselListNotifier extends AsyncNotifier<List<Vessel>> {
  @override
  Future<List<Vessel>> build() async {
    final api = ref.watch(userApiProvider);
    if (ref.watch(currentUserIdProvider) == null) return const [];
    return api.getVessels();
  }

  Future<Vessel> createVessel(VesselDraft draft) async {
    final vessel = await ref.read(userApiProvider).createVessel(draft);
    ref.invalidateSelf();
    return vessel;
  }

  Future<Vessel> updateVessel(String id, VesselDraft draft) async {
    final vessel = await ref.read(userApiProvider).updateVessel(id, draft);
    ref.invalidateSelf();
    ref.invalidate(vesselDetailProvider(id));
    return vessel;
  }

  Future<void> deleteVessel(String id) async {
    await ref.read(userApiProvider).deleteVessel(id);
    ref.invalidateSelf();
    ref.invalidate(vesselDetailProvider(id));
  }
}

/// One of the signed-in user's vessels (404 for anyone else's).
final vesselDetailProvider = FutureProvider.autoDispose.family<Vessel, String>((ref, id) {
  final api = ref.watch(userApiProvider);
  requireUserId(ref);
  return api.getVessel(id);
});

/// The vessel the shop evaluates fitment against: the user's explicit choice,
/// else their primary vessel, else none. Reset when the user changes.
final selectedVesselIdProvider =
    NotifierProvider<SelectedVesselNotifier, String?>(SelectedVesselNotifier.new);

class SelectedVesselNotifier extends Notifier<String?> {
  @override
  String? build() {
    ref.watch(currentUserIdProvider);
    return null;
  }

  void select(String? vesselId) => state = vesselId;
}

/// The resolved shopping vessel (choice → primary → first), or null.
final shoppingVesselProvider = Provider<Vessel?>((ref) {
  final vessels = ref.watch(vesselListProvider).value ?? const <Vessel>[];
  if (vessels.isEmpty) return null;
  final chosen = ref.watch(selectedVesselIdProvider);
  for (final v in vessels) {
    if (v.id == chosen) return v;
  }
  for (final v in vessels) {
    if (v.isPrimary) return v;
  }
  return vessels.first;
});
