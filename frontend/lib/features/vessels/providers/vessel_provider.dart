import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/models/vessel.dart';

/// Provider for the list of user vessels.
final vesselListProvider = AsyncNotifierProvider<VesselListNotifier, List<Vessel>>(
  VesselListNotifier.new,
);

class VesselListNotifier extends AsyncNotifier<List<Vessel>> {
  @override
  Future<List<Vessel>> build() async {
    final apiService = ref.read(apiServiceProvider);
    return apiService.getVessels();
  }

  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final apiService = ref.read(apiServiceProvider);
      return apiService.getVessels();
    });
  }

  Future<Vessel> createVessel(Map<String, dynamic> data) async {
    final apiService = ref.read(apiServiceProvider);
    final vessel = await apiService.createVessel(data);
    ref.invalidateSelf();
    return vessel;
  }

  Future<Vessel> updateVessel(String id, Map<String, dynamic> data) async {
    final apiService = ref.read(apiServiceProvider);
    final vessel = await apiService.updateVessel(id, data);
    ref.invalidateSelf();
    return vessel;
  }

  Future<void> deleteVessel(String id) async {
    final apiService = ref.read(apiServiceProvider);
    await apiService.deleteVessel(id);
    ref.invalidateSelf();
  }
}

/// Provider for a single vessel detail.
final vesselDetailProvider =
    FutureProvider.autoDispose.family<Vessel, String>((ref, id) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getVessel(id);
});
