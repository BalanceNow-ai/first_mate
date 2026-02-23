import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

/// Checklists for a specific vessel.
final vesselChecklistsProvider = FutureProvider.autoDispose
    .family<List<Map<String, dynamic>>, String>((ref, vesselId) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getVesselChecklists(vesselId);
});

/// Generate checklists for a vessel.
final generateChecklistsProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, String>((ref, vesselId) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.generateChecklists(vesselId);
});
