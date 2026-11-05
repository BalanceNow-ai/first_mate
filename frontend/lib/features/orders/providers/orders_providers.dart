import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/features/orders/data/commerce_api.dart';

/// One page of the signed-in user's orders (newest first).
final orderHistoryProvider = FutureProvider.autoDispose.family<OrderPage, int>((ref, page) {
  return ref.watch(commerceApiProvider).orders(page: page);
});

/// One of the user's orders.
final orderDetailProvider = FutureProvider.autoDispose.family<Order, String>((ref, id) {
  return ref.watch(commerceApiProvider).order(id);
});

/// The Helm Dash delivery belonging to an order, if one exists yet (it is
/// created once the order is paid).
final orderDeliveryProvider = FutureProvider.autoDispose.family<DeliveryTracking?, String>((ref, orderId) async {
  final deliveries = await ref.watch(commerceApiProvider).myDeliveries();
  for (final d in deliveries) {
    if (d.orderId == orderId) return d;
  }
  return null;
});
