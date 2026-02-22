import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/models/user.dart';

final apiServiceProvider = Provider<ApiService>((ref) {
  return ApiService(ref.watch(dioProvider));
});

class ApiService {
  final Dio _dio;

  ApiService(this._dio);

  // --- Auth ---

  Future<User> getCurrentUser() async {
    final response = await _dio.get('/auth/me');
    return User.fromJson(response.data);
  }

  Future<User> registerUser(Map<String, dynamic> data) async {
    final response = await _dio.post('/auth/register', data: data);
    return User.fromJson(response.data);
  }

  // --- Vessels ---

  Future<List<Vessel>> getVessels() async {
    final response = await _dio.get('/vessels/');
    return (response.data as List)
        .map((json) => Vessel.fromJson(json))
        .toList();
  }

  Future<Vessel> getVessel(String id) async {
    final response = await _dio.get('/vessels/$id');
    return Vessel.fromJson(response.data);
  }

  Future<Vessel> createVessel(Map<String, dynamic> data) async {
    final response = await _dio.post('/vessels/', data: data);
    return Vessel.fromJson(response.data);
  }

  Future<Vessel> updateVessel(String id, Map<String, dynamic> data) async {
    final response = await _dio.patch('/vessels/$id', data: data);
    return Vessel.fromJson(response.data);
  }

  Future<void> deleteVessel(String id) async {
    await _dio.delete('/vessels/$id');
  }

  // --- Products ---

  Future<List<Product>> getProducts({
    String? category,
    String? brand,
    String? vesselId,
    String? search,
    int offset = 0,
    int limit = 20,
  }) async {
    final params = <String, dynamic>{
      'offset': offset,
      'limit': limit,
    };
    if (category != null) params['category'] = category;
    if (brand != null) params['brand'] = brand;
    if (vesselId != null) params['vessel_id'] = vesselId;
    if (search != null) params['search'] = search;

    final response = await _dio.get('/products/', queryParameters: params);
    return (response.data as List)
        .map((json) => Product.fromJson(json))
        .toList();
  }

  Future<Product> getProduct(String id) async {
    final response = await _dio.get('/products/$id');
    return Product.fromJson(response.data);
  }

  Future<Map<String, dynamic>> checkCompatibility(
      String productId, String vesselId) async {
    final response = await _dio.get(
      '/products/$productId/check-compatibility',
      queryParameters: {'vessel_id': vesselId},
    );
    return response.data;
  }

  // --- AI Chat ---

  Future<Map<String, dynamic>> sendChatMessage({
    required String message,
    String? vesselId,
    String? conversationId,
  }) async {
    final data = <String, dynamic>{'message': message};
    if (vesselId != null) data['vessel_id'] = vesselId;
    if (conversationId != null) data['conversation_id'] = conversationId;

    final response = await _dio.post('/ai/chat', data: data);
    return response.data;
  }

  Future<List<Map<String, dynamic>>> getConversations() async {
    final response = await _dio.get('/ai/conversations');
    return (response.data as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> getConversation(String id) async {
    final response = await _dio.get('/ai/conversations/$id');
    return response.data;
  }

  // --- Cart ---

  Future<Map<String, dynamic>> getCart() async {
    final response = await _dio.get('/cart/');
    return response.data;
  }

  Future<void> addToCart(String productId, {int quantity = 1}) async {
    await _dio.post('/cart/items', data: {
      'product_id': productId,
      'quantity': quantity,
    });
  }

  // --- Orders ---

  Future<List<Map<String, dynamic>>> getOrders() async {
    final response = await _dio.get('/orders/');
    return (response.data as List).cast<Map<String, dynamic>>();
  }

  // --- Shipping ---

  Future<Map<String, dynamic>> getShippingRates(
      Map<String, dynamic> data) async {
    final response = await _dio.post('/shipping/rates', data: data);
    return response.data;
  }

  // --- Loyalty ---

  Future<Map<String, dynamic>> getCrewPoints() async {
    final response = await _dio.get('/loyalty/points');
    return response.data;
  }
}
