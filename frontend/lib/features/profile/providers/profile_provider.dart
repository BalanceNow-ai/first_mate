import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/session/session.dart';

/// Order history for the current user.
final orderHistoryProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.watch(userApiProvider);
  return apiService.getOrders();
});
