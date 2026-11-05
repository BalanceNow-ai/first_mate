import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/session/session.dart';

/// The signed-in user's cart, as computed by the server. Every mutation
/// replaces the state with the server's response (prices, subtotal, issues),
/// so the client never computes money. Reset whenever the user changes.
final cartProvider = AsyncNotifierProvider<CartNotifier, Cart>(CartNotifier.new);

class CartNotifier extends AsyncNotifier<Cart> {
  @override
  Future<Cart> build() async {
    final api = ref.watch(userApiProvider);
    if (ref.watch(currentUserIdProvider) == null) return Cart.empty;
    return api.getCart();
  }

  Future<Cart> _apply(Future<Cart> Function() change) async {
    final owner = ref.read(currentUserIdProvider);
    final cart = await change();
    // Ignore a response that arrives after the user changed.
    if (ref.mounted && ref.read(currentUserIdProvider) == owner) state = AsyncData(cart);
    return cart;
  }

  /// Adds [quantity] of a product. Throws `ApiError` (e.g. `insufficient_stock`).
  Future<Cart> add(String productId, {int quantity = 1}) =>
      _apply(() => ref.read(userApiProvider).addToCart(productId, quantity: quantity));

  Future<Cart> setQuantity(String itemId, int quantity) =>
      _apply(() => ref.read(userApiProvider).updateCartItem(itemId, quantity));

  Future<Cart> remove(String itemId) =>
      _apply(() => ref.read(userApiProvider).removeCartItem(itemId));

  Future<void> reload() async {
    ref.invalidateSelf();
    await future;
  }
}
