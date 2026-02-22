import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

/// Order history for the current user.
final orderHistoryProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getOrders();
});
