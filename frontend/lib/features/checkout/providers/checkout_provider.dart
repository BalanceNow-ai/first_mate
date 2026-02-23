import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

/// Cart data provider.
final cartProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getCart();
});

/// Checkout state managed across the 3-step flow.
class CheckoutState {
  final int currentStep;
  final String deliveryType; // courier, helm_dash, click_and_collect
  final Map<String, String> shippingAddress;
  final Map<String, double>? helmDashCoordinates;
  final String paymentMethod; // card, afterpay, laybuy
  final String? orderId;
  final String? clientSecret;
  final bool isProcessing;
  final String? error;

  const CheckoutState({
    this.currentStep = 0,
    this.deliveryType = 'courier',
    this.shippingAddress = const {},
    this.helmDashCoordinates,
    this.paymentMethod = 'card',
    this.orderId,
    this.clientSecret,
    this.isProcessing = false,
    this.error,
  });

  CheckoutState copyWith({
    int? currentStep,
    String? deliveryType,
    Map<String, String>? shippingAddress,
    Map<String, double>? helmDashCoordinates,
    String? paymentMethod,
    String? orderId,
    String? clientSecret,
    bool? isProcessing,
    String? error,
  }) {
    return CheckoutState(
      currentStep: currentStep ?? this.currentStep,
      deliveryType: deliveryType ?? this.deliveryType,
      shippingAddress: shippingAddress ?? this.shippingAddress,
      helmDashCoordinates: helmDashCoordinates ?? this.helmDashCoordinates,
      paymentMethod: paymentMethod ?? this.paymentMethod,
      orderId: orderId ?? this.orderId,
      clientSecret: clientSecret ?? this.clientSecret,
      isProcessing: isProcessing ?? this.isProcessing,
      error: error,
    );
  }
}

class CheckoutNotifier extends StateNotifier<CheckoutState> {
  final ApiService _apiService;

  CheckoutNotifier(this._apiService) : super(const CheckoutState());

  void setDeliveryType(String type) {
    state = state.copyWith(deliveryType: type);
  }

  void setShippingAddress(Map<String, String> address) {
    state = state.copyWith(shippingAddress: address);
  }

  void setHelmDashCoordinates(double lat, double lng) {
    state = state.copyWith(
      helmDashCoordinates: {'lat': lat, 'lng': lng},
    );
  }

  void setPaymentMethod(String method) {
    state = state.copyWith(paymentMethod: method);
  }

  void goToStep(int step) {
    state = state.copyWith(currentStep: step);
  }

  Future<bool> createOrder() async {
    state = state.copyWith(isProcessing: true, error: null);
    try {
      final orderData = <String, dynamic>{
        'delivery_type': state.deliveryType,
      };
      if (state.shippingAddress.isNotEmpty) {
        orderData['shipping_address'] = state.shippingAddress;
      }
      if (state.deliveryType == 'helm_dash' &&
          state.helmDashCoordinates != null) {
        orderData['helm_dash_coordinates'] = state.helmDashCoordinates;
      }

      final order = await _apiService.createOrder(orderData);
      final orderId = order['id'] as String;

      // Create payment intent
      final paymentResult = await _apiService.createPaymentIntent(orderId);
      final clientSecret = paymentResult['client_secret'] as String;

      state = state.copyWith(
        orderId: orderId,
        clientSecret: clientSecret,
        isProcessing: false,
      );
      return true;
    } catch (e) {
      state = state.copyWith(
        isProcessing: false,
        error: e.toString(),
      );
      return false;
    }
  }

  void confirmPayment() {
    state = state.copyWith(currentStep: 2);
  }

  void setError(String message) {
    state = state.copyWith(isProcessing: false, error: message);
  }

  void reset() {
    state = const CheckoutState();
  }
}

final checkoutProvider =
    StateNotifierProvider<CheckoutNotifier, CheckoutState>((ref) {
  return CheckoutNotifier(ref.read(apiServiceProvider));
});
