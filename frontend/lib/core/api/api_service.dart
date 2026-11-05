import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/config/public_config.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/models/vessel.dart';

final apiServiceProvider = Provider<ApiService>((ref) {
  return ApiService(ref.watch(dioProvider));
});

/// Typed access to the Helm API. Every failure surfaces as an [ApiError]
/// carrying the server's `{detail, code}`.
class ApiService {
  ApiService(this._dio);

  final Dio _dio;

  Future<T> _call<T>(Future<Response<dynamic>> Function() send, T Function(dynamic) parse) async {
    try {
      final response = await send();
      return parse(response.data);
    } on DioException catch (e) {
      throw ApiError.from(e)!;
    }
  }

  Map<String, dynamic> _map(dynamic data) => (data as Map).cast<String, dynamic>();

  List<Map<String, dynamic>> _list(dynamic data) =>
      [for (final e in data as List) (e as Map).cast<String, dynamic>()];

  // --- Configuration ---

  /// `GET /api/v1/config/public` (no authentication).
  Future<PublicConfig> getPublicConfig() => _call(
        () => _dio.get('/config/public',
            options: Options(extra: {AuthInterceptor.skipAuthKey: true})),
        (d) => PublicConfig.fromJson(_map(d)),
      );

  // --- Identity ---

  /// Idempotently creates the local profile for the signed-in subject. Only
  /// profile hints are sent — identity and role come from the verified token.
  Future<ProvisionResult> provision({String? fullName}) => _call(
        () => _dio.post('/auth/provision', data: {
          if (fullName != null && fullName.trim().isNotEmpty) 'full_name': fullName.trim(),
        }),
        (d) => ProvisionResult.fromJson(_map(d)),
      );

  Future<User> getCurrentUser() => _call(() => _dio.get('/auth/me'), (d) => User.fromJson(_map(d)));

  Future<User> updateProfile(UserUpdate update) => _call(
        () => _dio.patch('/users/me', data: update.toJson()),
        (d) => User.fromJson(_map(d)),
      );

  // --- Vessels ---

  Future<List<Vessel>> getVessels() => _call(
        () => _dio.get('/vessels/'),
        (d) => [for (final v in _list(d)) Vessel.fromJson(v)],
      );

  Future<Vessel> getVessel(String id) =>
      _call(() => _dio.get('/vessels/$id'), (d) => Vessel.fromJson(_map(d)));

  Future<Vessel> createVessel(VesselDraft draft) => _call(
        () => _dio.post('/vessels/', data: draft.toCreateJson()),
        (d) => Vessel.fromJson(_map(d)),
      );

  Future<Vessel> updateVessel(String id, VesselDraft draft) => _call(
        () => _dio.patch('/vessels/$id', data: draft.toUpdateJson()),
        (d) => Vessel.fromJson(_map(d)),
      );

  Future<void> deleteVessel(String id) => _call(() => _dio.delete('/vessels/$id'), (_) {});

  // --- Products: see features/products/data/catalogue_api.dart (CatalogueApi).

  // --- Cart ---

  Future<Cart> getCart() => _call(() => _dio.get('/cart/'), (d) => Cart.fromJson(_map(d)));

  Future<Cart> addToCart(String productId, {int quantity = 1}) => _call(
        () => _dio.post('/cart/items', data: {'product_id': productId, 'quantity': quantity}),
        (d) => Cart.fromJson(_map(d)),
      );

  Future<Cart> updateCartItem(String itemId, int quantity) => _call(
        () => _dio.patch('/cart/items/$itemId', data: {'quantity': quantity}),
        (d) => Cart.fromJson(_map(d)),
      );

  Future<Cart> removeCartItem(String itemId) =>
      _call(() => _dio.delete('/cart/items/$itemId'), (d) => Cart.fromJson(_map(d)));

  Future<void> clearCart() => _call(() => _dio.delete('/cart/'), (_) {});

  // --- Pass-2 screens: untyped until their contracts are merged -------------
  // TODO(client pass 2): replace these Map-based calls with typed models.

  Future<Map<String, dynamic>> sendChatMessage({
    required String message,
    String? vesselId,
    String? conversationId,
  }) =>
      _call(
        () => _dio.post('/ai/chat', data: {
          'message': message,
          'vessel_id': ?vesselId,
          'conversation_id': ?conversationId,
        }),
        _map,
      );

  Future<List<Map<String, dynamic>>> getConversations() =>
      _call(() => _dio.get('/ai/conversations'), _list);

  Future<Map<String, dynamic>> getConversation(String id) =>
      _call(() => _dio.get('/ai/conversations/$id'), _map);

  Future<List<Map<String, dynamic>>> getVesselChecklists(String vesselId) =>
      _call(() => _dio.get('/checklists/vessel/$vesselId'), _list);

  Future<Map<String, dynamic>> generateChecklists(String vesselId) =>
      _call(() => _dio.post('/checklists/vessel/$vesselId/generate'), _map);

  Future<Map<String, dynamic>> toggleChecklistItem(String itemId) =>
      _call(() => _dio.patch('/checklists/items/$itemId/toggle'), _map);

  Future<Map<String, dynamic>> linkProductToItem(String itemId, String productId) => _call(
        () => _dio.patch('/checklists/items/$itemId/link-product',
            data: {'product_id': productId}),
        _map,
      );

  Future<Map<String, dynamic>> addUncheckedToCart(String vesselId) =>
      _call(() => _dio.post('/checklists/vessel/$vesselId/add-unchecked-to-cart'), _map);

  Future<List<Map<String, dynamic>>> getOrders() => _call(() => _dio.get('/orders/'), _list);

  Future<Map<String, dynamic>> createOrder(Map<String, dynamic> data) =>
      _call(() => _dio.post('/orders/', data: data), _map);

  Future<Map<String, dynamic>> getOrder(String orderId) =>
      _call(() => _dio.get('/orders/$orderId'), _map);

  Future<Map<String, dynamic>> createPaymentIntent(String orderId) =>
      _call(() => _dio.post('/payments/$orderId/create-intent'), _map);

  Future<Map<String, dynamic>> getShippingRates(Map<String, dynamic> data) =>
      _call(() => _dio.post('/shipping/rates', data: data), _map);

  Future<List<Map<String, dynamic>>> getSignatureExperiences() =>
      _call(() => _dio.get('/loyalty/experiences'), _list);

  Future<Map<String, dynamic>> getCrewPoints() => _call(() => _dio.get('/loyalty/points'), _map);

  Future<Map<String, dynamic>> getCrewMultiplier() =>
      _call(() => _dio.get('/loyalty/multiplier'), _map);

  Future<List<Map<String, dynamic>>> getCrewTeams() =>
      _call(() => _dio.get('/loyalty/teams'), _list);

  Future<Map<String, dynamic>> redeemPoints(Map<String, dynamic> data) =>
      _call(() => _dio.post('/loyalty/points/redeem', data: data), _map);

  Future<Map<String, dynamic>> getHelmDashQuote(double lat, double lng) => _call(
        () => _dio.post('/helm-dash/quote', data: {'delivery_lat': lat, 'delivery_lng': lng}),
        _map,
      );

  Future<List<Map<String, dynamic>>> getHelmDashDeliveries() =>
      _call(() => _dio.get('/helm-dash/deliveries'), _list);

  Future<Map<String, dynamic>> getHelmDashDelivery(String id) =>
      _call(() => _dio.get('/helm-dash/deliveries/$id'), _map);
}
