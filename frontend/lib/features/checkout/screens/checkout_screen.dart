import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/checkout/payment/payment_panel.dart';
import 'package:helm_marine/features/checkout/providers/checkout_provider.dart';
import 'package:helm_marine/features/checkout/widgets/checkout_widgets.dart';
import 'package:helm_marine/features/checkout/widgets/helm_dash_pin_picker.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:latlong2/latlong.dart';

/// Checkout: delivery (server options + quote) → review (server preview,
/// discount, idempotent order) → payment. Every amount shown comes from the
/// server; the client never prices anything.
class CheckoutScreen extends ConsumerStatefulWidget {
  const CheckoutScreen({super.key});

  @override
  ConsumerState<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends ConsumerState<CheckoutScreen> {
  int _step = 0;
  final _courierForm = GlobalKey<FormState>();
  final _helmDashForm = GlobalKey<FormState>();

  // Courier address.
  final _name = TextEditingController();
  final _line1 = TextEditingController();
  final _line2 = TextEditingController();
  final _suburb = TextEditingController();
  final _city = TextEditingController();
  final _postcode = TextEditingController();
  final _phone = TextEditingController();

  // Helm Dash.
  LatLng? _pin;
  final _locationName = TextEditingController();
  final _vesselName = TextEditingController();
  final _hdPhone = TextEditingController();
  final _hdNote = TextEditingController();

  final _notes = TextEditingController();

  CheckoutController get _checkout => ref.read(checkoutProvider.notifier);

  @override
  void initState() {
    super.initState();
    if (ref.read(checkoutProvider).orderId != null) _step = 2;
  }

  @override
  void dispose() {
    for (final c in [_name, _line1, _line2, _suburb, _city, _postcode, _phone, _locationName, _vesselName, _hdPhone, _hdNote, _notes]) {
      c.dispose();
    }
    super.dispose();
  }

  // ----------------------------------------------------------------- requests

  static String? _required(String? v, String label) => (v == null || v.trim().isEmpty) ? '$label is required' : null;

  static String? _postcodeValidator(String? v) {
    if (v == null || v.trim().isEmpty) return 'Postcode is required';
    return ShippingAddress.postcodePattern.hasMatch(v.trim()) ? null : 'Enter a 4-digit NZ postcode';
  }

  static String? _phoneValidator(String? v) {
    if (v == null || v.trim().isEmpty) return 'Phone is required';
    return ShippingAddress.phonePattern.hasMatch(v.trim()) ? null : 'Enter a valid phone number';
  }

  ShippingAddress _address() => ShippingAddress(
        name: _name.text.trim(),
        line1: _line1.text.trim(),
        line2: _line2.text.trim(),
        suburb: _suburb.text.trim(),
        city: _city.text.trim(),
        postcode: _postcode.text.trim(),
        phone: _phone.text.trim(),
      );

  CheckoutRequest _request(CheckoutState s) {
    final type = s.deliveryType!;
    return CheckoutRequest(
      deliveryType: type,
      quoteId: type == DeliveryType.clickAndCollect ? null : s.quote?.id,
      shippingAddress: type == DeliveryType.courier ? _address() : null,
      helmDashContact: type == DeliveryType.helmDash
          ? HelmDashContact(vesselName: _vesselName.text.trim(), phone: _hdPhone.text.trim(), note: _hdNote.text.trim())
          : null,
      discountEntitlementId: s.entitlementId,
      notes: _notes.text,
    );
  }

  Future<void> _getCourierQuote() async {
    final postcode = _postcode.text.trim();
    if (_postcodeValidator(postcode) != null) {
      _courierForm.currentState?.validate();
      return;
    }
    await _checkout.quoteCourier(postcode: postcode, city: _city.text.trim(), suburb: _suburb.text.trim());
  }

  Future<void> _getHelmDashQuote() async {
    final pin = _pin;
    if (pin == null) return;
    await _checkout.quoteHelmDash(lat: pin.latitude, lng: pin.longitude, locationName: _locationName.text.trim());
  }

  void _requote() {
    final s = ref.read(checkoutProvider);
    setState(() => _step = 0);
    _checkout.clearQuote();
    if (s.deliveryType == DeliveryType.courier) {
      _getCourierQuote();
    } else if (s.deliveryType == DeliveryType.helmDash) {
      _getHelmDashQuote();
    }
  }

  bool _deliveryReady(CheckoutState s) {
    switch (s.deliveryType) {
      case DeliveryType.clickAndCollect:
        return true;
      case DeliveryType.courier:
      case DeliveryType.helmDash:
        return s.quote != null && !s.quote!.isExpired(ref.read(checkoutClockProvider)()) && !s.quoting;
      default:
        return false;
    }
  }

  void _continueToReview() {
    final s = ref.read(checkoutProvider);
    if (s.deliveryType == DeliveryType.courier && !(_courierForm.currentState?.validate() ?? false)) return;
    if (s.deliveryType == DeliveryType.helmDash && !(_helmDashForm.currentState?.validate() ?? false)) return;
    if (s.deliveryType == DeliveryType.courier && s.quote?.postcode != _postcode.text.trim()) {
      _checkout.clearQuote();
      return;
    }
    setState(() => _step = 1);
    _checkout.preview(_request(s));
  }

  Future<void> _placeOrder() async {
    final s = ref.read(checkoutProvider);
    final order = await _checkout.placeOrder(_request(s));
    if (order != null && mounted) setState(() => _step = 2);
  }

  void _finished() {
    _checkout.reset();
  }

  // ----------------------------------------------------------------- build

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(checkoutProvider);
    final cart = ref.watch(cartProvider);
    final step = s.orderId != null ? 2 : _step;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        leading: step == 1
            ? IconButton(
                tooltip: 'Back to delivery',
                icon: const Icon(Icons.arrow_back),
                onPressed: () => setState(() => _step = 0),
              )
            : null,
      ),
      body: ContentWidth(
        maxWidth: 820,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            CheckoutStepHeader(step: step),
            const SizedBox(height: 16),
            if (step == 2)
              PaymentPanel(orderId: s.orderId!, onFinished: _finished)
            else
              ...cart.when(
                loading: () => [const LoadingView(message: 'Loading your cart…')],
                error: (e, _) => [ErrorView(error: e, title: 'Could not load your cart', onRetry: () => ref.invalidate(cartProvider))],
                data: (c) {
                  if (c.isEmpty) {
                    return [
                      const Icon(Icons.shopping_cart_outlined, size: 56, color: HelmTheme.mutedText),
                      const SizedBox(height: 8),
                      const Text('Your cart is empty', textAlign: TextAlign.center),
                      const SizedBox(height: 8),
                      Center(child: FilledButton(onPressed: () => context.go('/products'), child: const Text('Shop parts'))),
                    ];
                  }
                  return step == 0 ? _deliveryStep(context, s, c) : _reviewStep(context, s, c);
                },
              ),
          ],
        ),
      ),
    );
  }

  Widget _cartSummary(Cart cart) {
    return Card(
      child: ExpansionTile(
        title: Text('Your cart (${cart.itemCount} ${cart.itemCount == 1 ? 'item' : 'items'})'),
        subtitle: Text('Subtotal ${formatCents(cart.subtotalCents)}'),
        children: [
          for (final l in cart.items)
            ListTile(
              dense: true,
              title: Text(l.product.name),
              subtitle: Text('${l.quantity} × ${formatCents(l.unitPriceCents)}'
                  '${l.product.dangerousGoods ? ' · dangerous goods' : ''}'),
              trailing: Text(formatCents(l.lineTotalCents)),
            ),
        ],
      ),
    );
  }

  List<Widget> _deliveryStep(BuildContext context, CheckoutState s, Cart cart) {
    final options = ref.watch(deliveryOptionsProvider);
    final theme = Theme.of(context);
    return [
      _cartSummary(cart),
      if (cart.hasIssues)
        CheckoutErrorCard(
          error: Exception('Some items in your cart need attention before you can check out.'),
          onBackToCart: () => context.go('/cart'),
        ),
      const SizedBox(height: 16),
      Semantics(header: true, child: Text('Delivery', style: theme.textTheme.titleLarge)),
      const SizedBox(height: 8),
      ...options.when(
        loading: () => [const LoadingView(message: 'Checking delivery options…')],
        error: (e, _) => [
          ErrorView(error: e, title: 'Could not load delivery options', onRetry: () => ref.invalidate(deliveryOptionsProvider)),
        ],
        data: (o) => [
          if (o.dangerousGoodsProducts.isNotEmpty)
            _InfoBanner(
              icon: Icons.warning_amber,
              color: HelmTheme.warning,
              text: 'Dangerous goods in your cart (${o.dangerousGoodsProducts.map((p) => p.name).join(', ')}) '
                  'limit the delivery methods available.',
            ),
          if (o.missingWeightProducts.isNotEmpty)
            _InfoBanner(
              icon: Icons.scale,
              color: HelmTheme.warning,
              text: 'Courier pricing needs product weights; missing for: '
                  '${o.missingWeightProducts.map((p) => p.name).join(', ')}.',
            ),
          for (final option in o.options)
            DeliveryOptionTile(
              option: option,
              selected: s.deliveryType == option.deliveryType,
              onSelect: () => _checkout.selectDelivery(option.deliveryType),
            ),
          const SizedBox(height: 12),
          if (s.deliveryType != null && o.option(s.deliveryType!) != null)
            ..._deliveryDetails(context, s, o.option(s.deliveryType!)!, cart),
        ],
      ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: _deliveryReady(s) && !cart.hasIssues ? _continueToReview : null,
        icon: const Icon(Icons.arrow_forward),
        label: const Text('Continue to review'),
      ),
    ];
  }

  List<Widget> _deliveryDetails(BuildContext context, CheckoutState s, DeliveryOption option, Cart cart) {
    if (!option.available) return const [];
    final quoteError = s.quoteError == null
        ? null
        : CheckoutErrorCard(
            error: s.quoteError!,
            cart: cart,
            onBackToCart: () => context.go('/cart'),
            onChangeDelivery: () => ref.invalidate(deliveryOptionsProvider),
          );
    switch (option.deliveryType) {
      case DeliveryType.clickAndCollect:
        return [
          Card(
            child: ListTile(
              leading: const Icon(Icons.store),
              title: const Text('Pickup location'),
              subtitle: Text(option.pickupLocation ?? 'Helm store'),
              trailing: Text('Shipping ${formatCents(option.priceCents ?? 0)}'),
            ),
          ),
        ];
      case DeliveryType.courier:
        return [
          Form(
            key: _courierForm,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Delivery address (New Zealand)', style: Theme.of(context).textTheme.titleMedium),
                _field(_name, 'Full name *', validator: (v) => _required(v, 'Name'), autofill: AutofillHints.name),
                _field(_line1, 'Street address *',
                    validator: (v) => _required(v, 'Street address'), autofill: AutofillHints.streetAddressLine1),
                _field(_line2, 'Apartment, unit (optional)', autofill: AutofillHints.streetAddressLine2),
                _field(_suburb, 'Suburb (optional)', autofill: AutofillHints.sublocality),
                _field(_city, 'Town or city *', validator: (v) => _required(v, 'City'), autofill: AutofillHints.addressCity),
                _field(
                  _postcode,
                  'Postcode *',
                  validator: _postcodeValidator,
                  keyboard: TextInputType.number,
                  formatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
                  autofill: AutofillHints.postalCode,
                  onChanged: (v) {
                    if (s.quote != null && s.quote!.postcode != v.trim()) _checkout.clearQuote();
                  },
                ),
                _field(_phone, 'Phone *', validator: _phoneValidator, keyboard: TextInputType.phone, autofill: AutofillHints.telephoneNumber),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: s.quoting ? null : _getCourierQuote,
                  icon: s.quoting
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.request_quote),
                  label: Text(s.quote == null ? 'Get courier quote' : 'Re-quote'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          if (s.quote != null) QuoteCard(quote: s.quote!, onRequote: _requote, now: ref.read(checkoutClockProvider)),
          ?quoteError,
        ];
      case DeliveryType.helmDash:
        final areas = option.operatingAreas;
        return [
          Text('Where should we deliver?', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          HelmDashPinPicker(
            areas: areas,
            value: _pin,
            onChanged: (p) {
              setState(() => _pin = p);
              _checkout.clearQuote();
            },
          ),
          Form(
            key: _helmDashForm,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _field(_locationName, 'Location name (e.g. bay or anchorage)', onChanged: (_) {
                  if (s.quote != null) _checkout.clearQuote();
                }),
                _field(_vesselName, 'Vessel name *', validator: (v) => _required(v, 'Vessel name')),
                _field(_hdPhone, 'Contact phone *', validator: _phoneValidator, keyboard: TextInputType.phone),
                _field(_hdNote, 'Note for the skipper (optional)'),
              ],
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: s.quoting || _pin == null ? null : _getHelmDashQuote,
            icon: s.quoting
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.request_quote),
            label: Text(_pin == null ? 'Place the pin to get a quote' : (s.quote == null ? 'Get Helm Dash quote' : 'Re-quote')),
          ),
          const SizedBox(height: 8),
          if (s.quote != null) QuoteCard(quote: s.quote!, onRequote: _requote, now: ref.read(checkoutClockProvider)),
          ?quoteError,
        ];
    }
    return const [];
  }

  Widget _field(
    TextEditingController c,
    String label, {
    String? Function(String?)? validator,
    TextInputType? keyboard,
    List<TextInputFormatter>? formatters,
    String? autofill,
    ValueChanged<String>? onChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: TextFormField(
        controller: c,
        decoration: InputDecoration(labelText: label),
        validator: validator,
        keyboardType: keyboard,
        inputFormatters: formatters,
        autofillHints: autofill == null ? null : [autofill],
        onChanged: onChanged,
      ),
    );
  }

  List<Widget> _reviewStep(BuildContext context, CheckoutState s, Cart cart) {
    final theme = Theme.of(context);
    final entitlements = ref.watch(issuedEntitlementsProvider);
    final preview = s.preview;
    return [
      _cartSummary(cart),
      const SizedBox(height: 12),
      Card(
        child: ListTile(
          leading: const Icon(Icons.local_shipping),
          title: Text(DeliveryType.label(s.deliveryType)),
          subtitle: Text(switch (s.deliveryType) {
            DeliveryType.courier => '${_line1.text}, ${_city.text} ${_postcode.text}',
            DeliveryType.helmDash => '${_locationName.text.isEmpty ? 'Pinned position' : _locationName.text} · '
                'vessel ${_vesselName.text}',
            _ => preview?.pickupLocation ?? 'Collect in store',
          }),
          trailing: TextButton(onPressed: () => setState(() => _step = 0), child: const Text('Change')),
        ),
      ),
      if (s.quote != null) QuoteCard(quote: s.quote!, onRequote: _requote, now: ref.read(checkoutClockProvider)),
      const SizedBox(height: 12),
      Semantics(header: true, child: Text('Crew Rewards discount', style: theme.textTheme.titleMedium)),
      entitlements.when(
        loading: () => const LinearProgressIndicator(),
        error: (e, _) => Text('Discounts could not be loaded: ${describeError(e)}'),
        data: (list) => _EntitlementPicker(
          entitlements: list,
          selected: s.entitlementId,
          onChanged: (id) {
            _checkout.selectEntitlement(id);
            _checkout.preview(_request(ref.read(checkoutProvider)));
          },
        ),
      ),
      const SizedBox(height: 8),
      TextField(
        controller: _notes,
        maxLength: 1000,
        decoration: const InputDecoration(labelText: 'Order notes (optional)'),
      ),
      const SizedBox(height: 8),
      Semantics(header: true, child: Text('Order total', style: theme.textTheme.titleMedium)),
      if (s.previewing) const LinearProgressIndicator(),
      if (preview != null)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: [
              AmountRow(label: 'Subtotal', value: formatCents(preview.subtotalCents)),
              if (preview.discountCents > 0)
                AmountRow(label: 'Discount', value: '-${formatCents(preview.discountCents)}', color: HelmTheme.success),
              AmountRow(
                label: switch (preview.deliveryType) {
                  DeliveryType.clickAndCollect => 'Shipping (click & collect)',
                  _ when preview.freeShippingApplied => 'Shipping (free over ${formatCents(preview.freeShippingThresholdCents)})',
                  _ => 'Shipping',
                },
                value: formatCents(preview.shippingCents),
              ),
              const Divider(),
              AmountRow(label: 'Total (${preview.currency})', value: formatCents(preview.totalCents), bold: true),
            ]),
          ),
        ),
      if (s.previewError != null)
        CheckoutErrorCard(
          error: s.previewError!,
          cart: cart,
          onRequote: _requote,
          onBackToCart: () => context.go('/cart'),
          onChangeDelivery: () => setState(() => _step = 0),
          onRetry: () => _checkout.preview(_request(s)),
        ),
      if (s.placeError != null)
        CheckoutErrorCard(
          error: s.placeError!,
          cart: cart,
          onRequote: _requote,
          onBackToCart: () => context.go('/cart'),
          onChangeDelivery: () => setState(() => _step = 0),
          onRetry: _placeOrder,
        ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: s.placing || preview == null || s.previewing ? null : _placeOrder,
        icon: s.placing
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
            : const Icon(Icons.lock),
        label: Text(s.placing ? 'Placing order…' : 'Place order${preview == null ? '' : ' · ${formatCents(preview.totalCents)}'}'),
      ),
      const SizedBox(height: 4),
      Text('Placing the order reserves the stock; you pay on the next step.', style: theme.textTheme.bodySmall),
    ];
  }
}

class _EntitlementPicker extends StatelessWidget {
  const _EntitlementPicker({required this.entitlements, required this.selected, required this.onChanged});

  final List<DiscountEntitlement> entitlements;
  final String? selected;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    if (entitlements.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text('You have no unused Crew Rewards discounts.'),
      );
    }
    return RadioGroup<String?>(
      groupValue: selected,
      onChanged: onChanged,
      child: Column(
        children: [
          const RadioListTile<String?>(value: null, title: Text('No discount')),
          for (final e in entitlements)
            RadioListTile<String?>(
              value: e.id,
              title: Text('${formatCents(e.amountCents)} off'),
              subtitle: Text('Code ${e.code} · ${e.pointsCost} points'),
            ),
        ],
      ),
    );
  }
}

class _InfoBanner extends StatelessWidget {
  const _InfoBanner({required this.icon, required this.color, required this.text});

  final IconData icon;
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: tintedCardColor(color),
      child: ListTile(leading: Icon(icon, color: color), title: Text(text)),
    );
  }
}
