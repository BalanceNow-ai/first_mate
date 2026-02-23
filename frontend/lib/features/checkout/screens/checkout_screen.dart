import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_stripe/flutter_stripe.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';
import 'package:helm_marine/main.dart';

class CheckoutScreen extends ConsumerStatefulWidget {
  const CheckoutScreen({super.key});

  @override
  ConsumerState<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends ConsumerState<CheckoutScreen> {
  final _pageController = PageController();
  final _formKey = GlobalKey<FormState>();

  // Shipping form controllers
  final _nameController = TextEditingController();
  final _addressLine1Controller = TextEditingController();
  final _addressLine2Controller = TextEditingController();
  final _cityController = TextEditingController();
  final _postcodeController = TextEditingController();
  final _phoneController = TextEditingController();

  @override
  void dispose() {
    _pageController.dispose();
    _nameController.dispose();
    _addressLine1Controller.dispose();
    _addressLine2Controller.dispose();
    _cityController.dispose();
    _postcodeController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  void _goToPage(int page) {
    _pageController.animateToPage(
      page,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
    );
    ref.read(checkoutProvider.notifier).goToStep(page);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(checkoutProvider);
    final cartState = ref.watch(cartProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        leading: state.currentStep > 0 && state.currentStep < 2
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                tooltip: 'Go back',
                onPressed: () => _goToPage(state.currentStep - 1),
              )
            : null,
      ),
      body: Column(
        children: [
          // Step indicator
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _StepDot(label: 'Shipping', index: 0, current: state.currentStep),
                Expanded(
                  child: Container(
                    height: 2,
                    color: state.currentStep >= 1
                        ? HelmTheme.primary
                        : Colors.grey[300],
                  ),
                ),
                _StepDot(label: 'Payment', index: 1, current: state.currentStep),
                Expanded(
                  child: Container(
                    height: 2,
                    color: state.currentStep >= 2
                        ? HelmTheme.primary
                        : Colors.grey[300],
                  ),
                ),
                _StepDot(
                    label: 'Confirm', index: 2, current: state.currentStep),
              ],
            ),
          ),

          // Pages
          Expanded(
            child: PageView(
              controller: _pageController,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                _ShippingStep(
                  formKey: _formKey,
                  nameController: _nameController,
                  addressLine1Controller: _addressLine1Controller,
                  addressLine2Controller: _addressLine2Controller,
                  cityController: _cityController,
                  postcodeController: _postcodeController,
                  phoneController: _phoneController,
                  deliveryType: state.deliveryType,
                  onDeliveryTypeChanged: (type) {
                    ref.read(checkoutProvider.notifier).setDeliveryType(type);
                  },
                  onContinue: () {
                    if (_formKey.currentState!.validate() ||
                        state.deliveryType == 'helm_dash') {
                      ref
                          .read(checkoutProvider.notifier)
                          .setShippingAddress({
                        'name': _nameController.text,
                        'line1': _addressLine1Controller.text,
                        'line2': _addressLine2Controller.text,
                        'city': _cityController.text,
                        'postcode': _postcodeController.text,
                        'phone': _phoneController.text,
                        'country': 'NZ',
                      });
                      _goToPage(1);
                    }
                  },
                  cartState: cartState,
                ),
                _PaymentStep(
                  paymentMethod: state.paymentMethod,
                  onPaymentMethodChanged: (method) {
                    ref
                        .read(checkoutProvider.notifier)
                        .setPaymentMethod(method);
                  },
                  isProcessing: state.isProcessing,
                  error: state.error,
                  clientSecret: state.clientSecret,
                  onConfirmOrder: () async {
                    final notifier = ref.read(checkoutProvider.notifier);
                    final success = await notifier.createOrder();
                    if (success) {
                      // Confirm payment with Stripe
                      try {
                        final cs =
                            ref.read(checkoutProvider).clientSecret;
                        if (cs != null) {
                          await Stripe.instance.confirmPayment(
                            paymentIntentClientSecret: cs,
                          );
                        }
                        notifier.confirmPayment();
                        posthog.capture(eventName: 'order_completed', properties: {
                          'order_id': ref.read(checkoutProvider).orderId,
                        });
                        _goToPage(2);
                      } on StripeException catch (e) {
                        notifier.setError(
                          e.error.localizedMessage ?? 'Payment failed',
                        );
                      }
                    }
                  },
                  cartState: cartState,
                ),
                _ConfirmationStep(
                  orderId: state.orderId,
                  onTrackOrder: () {
                    if (state.orderId != null) {
                      ref.read(checkoutProvider.notifier).reset();
                      context.go('/orders/${state.orderId}');
                    }
                  },
                  onBackToHome: () {
                    ref.read(checkoutProvider.notifier).reset();
                    ref.invalidate(cartProvider);
                    context.go('/');
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StepDot extends StatelessWidget {
  final String label;
  final int index;
  final int current;

  const _StepDot({
    required this.label,
    required this.index,
    required this.current,
  });

  @override
  Widget build(BuildContext context) {
    final isActive = index <= current;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isActive ? HelmTheme.primary : Colors.grey[300],
          ),
          child: Center(
            child: index < current
                ? const Icon(Icons.check, size: 16, color: Colors.white)
                : Text(
                    '${index + 1}',
                    style: TextStyle(
                      color: isActive ? Colors.white : Colors.grey[600],
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 11,
            color: isActive ? HelmTheme.primary : Colors.grey[500],
            fontWeight: isActive ? FontWeight.w600 : FontWeight.normal,
          ),
        ),
      ],
    );
  }
}

// --- Step 1: Shipping ---

class _ShippingStep extends StatelessWidget {
  final GlobalKey<FormState> formKey;
  final TextEditingController nameController;
  final TextEditingController addressLine1Controller;
  final TextEditingController addressLine2Controller;
  final TextEditingController cityController;
  final TextEditingController postcodeController;
  final TextEditingController phoneController;
  final String deliveryType;
  final ValueChanged<String> onDeliveryTypeChanged;
  final VoidCallback onContinue;
  final AsyncValue<Map<String, dynamic>> cartState;

  const _ShippingStep({
    required this.formKey,
    required this.nameController,
    required this.addressLine1Controller,
    required this.addressLine2Controller,
    required this.cityController,
    required this.postcodeController,
    required this.phoneController,
    required this.deliveryType,
    required this.onDeliveryTypeChanged,
    required this.onContinue,
    required this.cartState,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Delivery method
        Text(
          'Delivery Method',
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 12),
        _DeliveryOption(
          title: 'Standard Shipping',
          subtitle: 'NZ Post / Aramex — 2-5 business days',
          icon: Icons.local_shipping,
          isSelected: deliveryType == 'courier',
          onTap: () => onDeliveryTypeChanged('courier'),
        ),
        const SizedBox(height: 8),
        _DeliveryOption(
          title: 'Helm Dash',
          subtitle: 'Maritime delivery direct to your vessel',
          icon: Icons.directions_boat,
          isSelected: deliveryType == 'helm_dash',
          onTap: () => onDeliveryTypeChanged('helm_dash'),
        ),
        const SizedBox(height: 8),
        _DeliveryOption(
          title: 'Click & Collect',
          subtitle: 'Pick up from Westhaven Marina',
          icon: Icons.store,
          isSelected: deliveryType == 'click_and_collect',
          onTap: () => onDeliveryTypeChanged('click_and_collect'),
        ),
        const SizedBox(height: 24),

        // Helm Dash map hint
        if (deliveryType == 'helm_dash') ...[
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: HelmTheme.accent.withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: HelmTheme.accent.withOpacity(0.3)),
            ),
            child: const Column(
              children: [
                Icon(Icons.map, size: 40, color: HelmTheme.accent),
                SizedBox(height: 8),
                Text(
                  'Drop a pin on the map to set your delivery location. '
                  'Your delivery fee will be calculated based on the distance.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: HelmTheme.accent, fontSize: 13),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],

        // Shipping address form
        if (deliveryType == 'courier') ...[
          Text(
            'Shipping Address',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          Form(
            key: formKey,
            child: Column(
              children: [
                TextFormField(
                  controller: nameController,
                  decoration: const InputDecoration(
                    labelText: 'Full Name',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) =>
                      v == null || v.isEmpty ? 'Name is required' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: addressLine1Controller,
                  decoration: const InputDecoration(
                    labelText: 'Address Line 1',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) =>
                      v == null || v.isEmpty ? 'Address is required' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: addressLine2Controller,
                  decoration: const InputDecoration(
                    labelText: 'Address Line 2 (optional)',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      flex: 2,
                      child: TextFormField(
                        controller: cityController,
                        decoration: const InputDecoration(
                          labelText: 'City',
                          border: OutlineInputBorder(),
                        ),
                        validator: (v) =>
                            v == null || v.isEmpty ? 'City is required' : null,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextFormField(
                        controller: postcodeController,
                        decoration: const InputDecoration(
                          labelText: 'Postcode',
                          border: OutlineInputBorder(),
                        ),
                        validator: (v) => v == null || v.isEmpty
                            ? 'Required'
                            : null,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: phoneController,
                  decoration: const InputDecoration(
                    labelText: 'Phone',
                    border: OutlineInputBorder(),
                    prefixText: '+64 ',
                  ),
                  keyboardType: TextInputType.phone,
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],

        // Cart summary
        cartState.whenOrNull(
          data: (cart) {
            final subtotal =
                (cart['subtotal'] as num?)?.toDouble() ?? 0;
            final itemCount = cart['item_count'] as int? ?? 0;
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Order Summary',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.bold,
                            )),
                    const Divider(),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('$itemCount items'),
                        Text('\$${subtotal.toStringAsFixed(2)}'),
                      ],
                    ),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Shipping'),
                        Text(subtotal >= 150
                            ? 'FREE'
                            : '\$9.90'),
                      ],
                    ),
                    const Divider(),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Total',
                            style: TextStyle(fontWeight: FontWeight.bold)),
                        Text(
                          '\$${(subtotal + (subtotal >= 150 ? 0 : 9.90)).toStringAsFixed(2)}',
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            color: HelmTheme.primary,
                            fontSize: 18,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          },
        ) ?? const SizedBox.shrink(),
        const SizedBox(height: 16),

        // Continue button
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: onContinue,
            child: const Text('Continue to Payment'),
          ),
        ),
      ],
    );
  }
}

class _DeliveryOption extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onTap;

  const _DeliveryOption({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? HelmTheme.primary : Colors.grey[300]!,
            width: isSelected ? 2 : 1,
          ),
          color: isSelected ? HelmTheme.primary.withOpacity(0.05) : null,
        ),
        child: Row(
          children: [
            Icon(icon,
                color: isSelected ? HelmTheme.primary : Colors.grey[600]),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: isSelected ? HelmTheme.primary : null,
                      )),
                  Text(subtitle,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey[600],
                      )),
                ],
              ),
            ),
            if (isSelected)
              const Icon(Icons.check_circle, color: HelmTheme.primary),
          ],
        ),
      ),
    );
  }
}

// --- Step 2: Payment ---

class _PaymentStep extends StatelessWidget {
  final String paymentMethod;
  final ValueChanged<String> onPaymentMethodChanged;
  final bool isProcessing;
  final String? error;
  final String? clientSecret;
  final VoidCallback onConfirmOrder;
  final AsyncValue<Map<String, dynamic>> cartState;

  const _PaymentStep({
    required this.paymentMethod,
    required this.onPaymentMethodChanged,
    required this.isProcessing,
    this.error,
    this.clientSecret,
    required this.onConfirmOrder,
    required this.cartState,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Payment Method',
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 12),

        // Payment options
        _PaymentOption(
          title: 'Credit / Debit Card',
          subtitle: 'Visa, Mastercard, AMEX',
          icon: Icons.credit_card,
          isSelected: paymentMethod == 'card',
          onTap: () => onPaymentMethodChanged('card'),
        ),
        const SizedBox(height: 8),
        _PaymentOption(
          title: 'Afterpay',
          subtitle: 'Pay in 4 interest-free instalments',
          icon: Icons.schedule,
          isSelected: paymentMethod == 'afterpay',
          onTap: () => onPaymentMethodChanged('afterpay'),
        ),
        const SizedBox(height: 8),
        _PaymentOption(
          title: 'Laybuy',
          subtitle: 'Pay over 6 weekly payments',
          icon: Icons.payments,
          isSelected: paymentMethod == 'laybuy',
          onTap: () => onPaymentMethodChanged('laybuy'),
        ),
        const SizedBox(height: 24),

        // Stripe card input
        if (paymentMethod == 'card') ...[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Card Details',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          )),
                  const SizedBox(height: 12),
                  const CardField(
                    enablePostalCode: true,
                    decoration: InputDecoration(
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Powered by Stripe. Your card details are encrypted.',
                    style: TextStyle(fontSize: 12, color: Colors.grey[500]),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
        ],

        // Order total
        cartState.whenOrNull(
          data: (cart) {
            final subtotal =
                (cart['subtotal'] as num?)?.toDouble() ?? 0;
            final shipping = subtotal >= 150 ? 0.0 : 9.90;
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Total',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 18,
                        )),
                    Text(
                      '\$${(subtotal + shipping).toStringAsFixed(2)} NZD',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        color: HelmTheme.primary,
                        fontSize: 18,
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ) ?? const SizedBox.shrink(),
        const SizedBox(height: 16),

        // Error
        if (error != null) ...[
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: HelmTheme.error.withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(error!, style: const TextStyle(color: HelmTheme.error)),
          ),
          const SizedBox(height: 16),
        ],

        // Confirm button
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: isProcessing ? null : onConfirmOrder,
            child: isProcessing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Text('Confirm Order'),
          ),
        ),
      ],
    );
  }
}

class _PaymentOption extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onTap;

  const _PaymentOption({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? HelmTheme.primary : Colors.grey[300]!,
            width: isSelected ? 2 : 1,
          ),
          color: isSelected ? HelmTheme.primary.withOpacity(0.05) : null,
        ),
        child: Row(
          children: [
            Icon(icon,
                color: isSelected ? HelmTheme.primary : Colors.grey[600]),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: isSelected ? HelmTheme.primary : null,
                      )),
                  Text(subtitle,
                      style: TextStyle(fontSize: 12, color: Colors.grey[600])),
                ],
              ),
            ),
            if (isSelected)
              const Icon(Icons.check_circle, color: HelmTheme.primary),
          ],
        ),
      ),
    );
  }
}

// --- Step 3: Confirmation ---

class _ConfirmationStep extends StatelessWidget {
  final String? orderId;
  final VoidCallback onTrackOrder;
  final VoidCallback onBackToHome;

  const _ConfirmationStep({
    this.orderId,
    required this.onTrackOrder,
    required this.onBackToHome,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: HelmTheme.success.withOpacity(0.1),
              ),
              child:
                  const Icon(Icons.check_circle, size: 64, color: HelmTheme.success),
            ),
            const SizedBox(height: 24),
            Text(
              'Order Confirmed!',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              'Thank you for your order',
              style: TextStyle(color: Colors.grey[600], fontSize: 16),
            ),
            if (orderId != null) ...[
              const SizedBox(height: 16),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'Order #${orderId!.substring(0, 8).toUpperCase()}',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontFamily: 'monospace',
                    fontSize: 16,
                  ),
                ),
              ),
            ],
            const SizedBox(height: 32),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: onTrackOrder,
                icon: const Icon(Icons.local_shipping),
                label: const Text('Track Order'),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                onPressed: onBackToHome,
                child: const Text('Back to Home'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
