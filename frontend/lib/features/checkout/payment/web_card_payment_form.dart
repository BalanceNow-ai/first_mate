import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';
import 'package:helm_marine/features/checkout/payment/web_card_payment_controller.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart' show tintedCardColor;

/// Web card payment: Stripe's Payment Element (card only) in a platform view
/// and a "Pay" button that confirms the order's PaymentIntent. After Stripe
/// accepts a confirmation, [onSubmitted] polls the server's order; this widget
/// never decides that the order is paid.
class WebCardPaymentForm extends StatefulWidget {
  const WebCardPaymentForm({
    super.key,
    required this.createBridge,
    required this.orderId,
    required this.clientSecret,
    required this.publishableKey,
    required this.payLabel,
    required this.onSubmitted,
    this.disabled = false,
  });

  final StripeWebBridgeFactory createBridge;
  final String orderId;
  final String clientSecret;
  final String? publishableKey;
  final String payLabel;
  final Future<void> Function() onSubmitted;

  /// Another payment action is in flight (cancel, polling…).
  final bool disabled;

  @override
  State<WebCardPaymentForm> createState() => _WebCardPaymentFormState();
}

class _WebCardPaymentFormState extends State<WebCardPaymentForm> with AutomaticKeepAliveClientMixin {
  late WebCardPaymentController _controller;

  @override
  void initState() {
    super.initState();
    _controller = _create();
  }

  WebCardPaymentController _create() {
    final c = WebCardPaymentController(
      bridge: widget.createBridge(),
      orderId: widget.orderId,
      clientSecret: widget.clientSecret,
      publishableKey: widget.publishableKey,
      onSubmitted: () => widget.onSubmitted(),
    );
    c.start();
    return c;
  }

  @override
  void didUpdateWidget(WebCardPaymentForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.clientSecret != widget.clientSecret || oldWidget.publishableKey != widget.publishableKey) {
      _controller.dispose();
      _controller = _create();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  bool get _testKey => widget.publishableKey?.startsWith('pk_test_') ?? false;

  /// Keep the mounted Payment Element when a lazy list scrolls it away.
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return ListenableBuilder(
      listenable: _controller,
      builder: (context, _) {
        final c = _controller;
        final theme = Theme.of(context);
        if (c.phase == WebCardPhase.unavailable) {
          return _Unavailable(reason: c.unavailableReason, onRetry: c.retry);
        }
        if (c.phase == WebCardPhase.loadingScript) {
          return Semantics(
            liveRegion: true,
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Row(children: [
                SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5)),
                SizedBox(width: 12),
                Expanded(child: Text('Loading secure card payment…')),
              ]),
            ),
          );
        }
        final mounting = c.phase == WebCardPhase.awaitingHost || c.phase == WebCardPhase.mounting;
        final confirming = c.phase == WebCardPhase.confirming;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(header: true, child: Text('Card details', style: theme.textTheme.titleMedium)),
            const SizedBox(height: 4),
            Text(
              'Your card details go directly to Stripe and never pass through Helm.',
              style: theme.textTheme.bodySmall,
            ),
            if (_testKey) ...[
              const SizedBox(height: 4),
              Text('Stripe test mode — use a Stripe test card; no real charge.',
                  style: theme.textTheme.bodySmall?.copyWith(color: HelmTheme.warning, fontWeight: FontWeight.bold)),
            ],
            const SizedBox(height: 8),
            // A fixed slot, so the host below keeps its element (and its
            // mounted Payment Element) when the progress bar goes away.
            SizedBox(
              height: 8,
              child: mounting
                  ? Semantics(
                      liveRegion: true,
                      label: 'Loading the secure card form',
                      child: const Align(alignment: Alignment.topCenter, child: LinearProgressIndicator()),
                    )
                  : null,
            ),
            Semantics(
              key: const ValueKey('stripe-payment-element-host'),
              container: true,
              label: 'Card details, secured by Stripe',
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                height: c.height,
                decoration: BoxDecoration(
                  border: Border.all(color: theme.dividerColor),
                  borderRadius: BorderRadius.circular(12),
                ),
                clipBehavior: Clip.antiAlias,
                child: AbsorbPointer(
                  absorbing: confirming || c.phase == WebCardPhase.submitted,
                  child: c.bridge.buildHost(onCreated: c.attachHost),
                ),
              ),
            ),
            if (c.cardError != null) ...[
              const SizedBox(height: 8),
              Semantics(
                liveRegion: true,
                container: true,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.error_outline, color: HelmTheme.error),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${c.cardError!} Nothing was charged — check the card details and try again.',
                        style: theme.textTheme.bodyMedium?.copyWith(color: HelmTheme.error),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: c.canPay && !widget.disabled ? c.pay : null,
              icon: confirming
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.lock),
              label: Text(confirming ? 'Confirming with your bank…' : widget.payLabel),
            ),
          ],
        );
      },
    );
  }
}

class _Unavailable extends StatelessWidget {
  const _Unavailable({required this.reason, required this.onRetry});

  final String? reason;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      liveRegion: true,
      container: true,
      child: Card(
        color: tintedCardColor(HelmTheme.warning),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.credit_card_off, color: HelmTheme.warning),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Card payments are unavailable right now',
                        style: theme.textTheme.titleSmall?.copyWith(color: HelmTheme.warning)),
                    const SizedBox(height: 4),
                    Text('${reason ?? 'The secure card form could not be loaded.'} '
                        'Nothing was charged and your order is still reserved.'),
                    const SizedBox(height: 8),
                    FilledButton.icon(
                      onPressed: onRetry,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Try again'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
