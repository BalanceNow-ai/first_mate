import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/config/public_config.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:helm_marine/core/models/order.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';
import 'package:helm_marine/features/checkout/payment/payment_readiness.dart';
import 'package:helm_marine/features/checkout/payment/stripe_payment.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';
import 'package:helm_marine/features/checkout/payment/web_card_payment_form.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';

/// Pays for one order: payment methods from `/config/public`, the provider's
/// confirmation (local TEST MODE panel or Stripe), then the server's verdict.
class PaymentPanel extends ConsumerStatefulWidget {
  const PaymentPanel({super.key, required this.orderId, this.onFinished});

  final String orderId;

  /// Called when the user leaves after a terminal outcome (paid / cancelled).
  final VoidCallback? onFinished;

  @override
  ConsumerState<PaymentPanel> createState() => _PaymentPanelState();
}

class _PaymentPanelState extends ConsumerState<PaymentPanel> {
  bool _retrying = false;

  PaymentController get _controller => ref.read(paymentControllerProvider(widget.orderId).notifier);

  Future<void> _confirmCancel() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Cancel this order?'),
        content: const Text(
            'The reserved stock is released and the items go back to your cart. Any discount you used is restored.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep order')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: HelmTheme.error),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Cancel order'),
          ),
        ],
      ),
    );
    if (ok == true) await _controller.cancel();
  }

  Future<void> _payWithStripe(PaymentsConfig payments, PaymentIntentInfo intent) async {
    final key = intent.publishableKey ?? payments.stripePublishableKey;
    if (key == null || key.isEmpty) {
      _controller.reportError(StateError('Stripe is not configured (no publishable key).'));
      return;
    }
    _controller.setBusy(true);
    try {
      final result = await presentStripePaymentSheet(publishableKey: key, clientSecret: intent.clientSecret);
      _controller.setBusy(false);
      if (result == StripeConfirmation.submitted) {
        setState(() => _retrying = false);
        await _controller.awaitServerResult();
      }
    } catch (e) {
      _controller.setBusy(false);
      _controller.reportError(StateError(describeStripeError(e)));
      await _controller.refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(paymentControllerProvider(widget.orderId));
    final config = ref.watch(publicConfigProvider);
    final order = state.order;

    if (order == null) {
      if (state.loadError != null) {
        return ErrorView(
          error: state.loadError!,
          title: 'Could not load the order',
          onRetry: _controller.load,
        );
      }
      return const Padding(padding: EdgeInsets.all(32), child: LoadingView(message: 'Loading payment…'));
    }

    final phase = state.phase;
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text('Pay for order ${order.orderNumber}', style: theme.textTheme.titleLarge),
        ),
        const SizedBox(height: 4),
        Text('Total ${formatCents(order.totalCents)} ${order.currency}', style: theme.textTheme.titleMedium),
        const SizedBox(height: 4),
        StatusChips(order: order),
        if (order.isPendingPayment && order.expiresAt != null) ...[
          const SizedBox(height: 12),
          ReservationCountdown(expiresAt: order.expiresAt!, onExpired: _controller.refresh),
        ],
        const SizedBox(height: 16),
        ..._phaseSection(context, state, phase, order, config.value),
        if (state.error != null) ...[
          const SizedBox(height: 12),
          _Notice(
            icon: Icons.error_outline,
            color: HelmTheme.error,
            title: 'Something went wrong',
            message: paymentErrorText(state.error!),
          ),
        ],
        if (order.canCancel && phase != PaymentPhase.paid) ...[
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: state.busy ? null : _confirmCancel,
            icon: const Icon(Icons.cancel_outlined),
            style: OutlinedButton.styleFrom(foregroundColor: HelmTheme.error),
            label: const Text('Cancel order'),
          ),
          const SizedBox(height: 4),
          Text('Cancelling releases the reservation and returns the items to your cart.',
              style: theme.textTheme.bodySmall),
        ],
      ],
    );
  }

  List<Widget> _phaseSection(
    BuildContext context,
    PaymentState state,
    PaymentPhase phase,
    Order order,
    PublicConfig? config,
  ) {
    switch (phase) {
      case PaymentPhase.paid:
        return [
          _Notice(
            icon: Icons.check_circle,
            color: HelmTheme.success,
            title: 'Payment confirmed',
            message: 'Helm received confirmation from the payment provider. Order ${order.orderNumber} is paid.',
            liveRegion: true,
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () {
              widget.onFinished?.call();
              context.go('/orders/${order.id}');
            },
            icon: const Icon(Icons.receipt_long),
            label: const Text('View order'),
          ),
        ];
      case PaymentPhase.underReview:
        return [
          _Notice(
            icon: Icons.manage_search,
            color: HelmTheme.warning,
            title: 'Payment under review',
            message: 'Payment received but the order needs staff review; you\'ll be contacted or refunded. '
                'Order ${order.orderNumber} is not confirmed yet — please don\'t pay again.',
            liveRegion: true,
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () {
              widget.onFinished?.call();
              context.go('/orders/${order.id}');
            },
            icon: const Icon(Icons.receipt_long),
            label: const Text('View order'),
          ),
        ];
      case PaymentPhase.cancelled:
        return [
          const _Notice(
            icon: Icons.remove_shopping_cart,
            color: HelmTheme.mutedText,
            title: 'Order cancelled',
            message: 'The reservation was released and the items are back in your cart.',
            liveRegion: true,
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: () {
              widget.onFinished?.call();
              context.go('/cart');
            },
            child: const Text('Back to cart'),
          ),
        ];
      case PaymentPhase.expired:
        return [
          const _Notice(
            icon: Icons.timer_off,
            color: HelmTheme.warning,
            title: 'Reservation expired',
            message: 'This order was not paid in time. The stock was released and the items returned to your cart.',
            liveRegion: true,
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: () {
              widget.onFinished?.call();
              context.go('/cart');
            },
            child: const Text('Back to cart'),
          ),
        ];
      case PaymentPhase.closed:
        return [
          _Notice(
            icon: Icons.info_outline,
            color: HelmTheme.mutedText,
            title: orderStatusLabel(order.status),
            message: 'This order is no longer awaiting payment.',
          ),
        ];
      case PaymentPhase.loading:
      case PaymentPhase.error:
        return const [];
      case PaymentPhase.ready:
      case PaymentPhase.processing:
      case PaymentPhase.failed:
      case PaymentPhase.requiresAction:
        break;
    }

    final out = <Widget>[];
    if (state.waiting || phase == PaymentPhase.processing) {
      out.add(const _Notice(
        icon: Icons.hourglass_top,
        color: HelmTheme.ocean,
        title: 'Waiting for confirmation',
        message: 'Checking with Helm for the payment provider\'s result…',
        busy: true,
        liveRegion: true,
      ));
      out.add(const SizedBox(height: 12));
    } else if (state.waitTimedOut) {
      out.add(_Notice(
        icon: Icons.schedule,
        color: HelmTheme.warning,
        title: 'No confirmation yet',
        message: 'The payment provider has not confirmed this payment yet. It can take a moment — check again shortly.',
        action: TextButton(onPressed: _controller.refresh, child: const Text('Check again')),
      ));
      out.add(const SizedBox(height: 12));
    }

    if (phase == PaymentPhase.failed && !_retrying) {
      out.add(_Notice(
        icon: Icons.credit_card_off,
        color: HelmTheme.error,
        title: 'Payment declined',
        message: 'Your card was declined and nothing was charged. Your items are still reserved — you can try again.',
        liveRegion: true,
        action: order.canRetryPayment
            ? FilledButton(
                onPressed: state.busy
                    ? null
                    : () async {
                        await _controller.retry();
                        if (mounted) setState(() => _retrying = true);
                      },
                child: const Text('Try again'),
              )
            : null,
      ));
      return out;
    }

    if (!order.canRetryPayment) {
      out.add(const _Notice(
        icon: Icons.block,
        color: HelmTheme.mutedText,
        title: 'Payment unavailable',
        message: 'This order cannot be paid right now (payments are unavailable or the reservation has ended).',
      ));
      return out;
    }

    final payments = config?.payments;
    out.add(PaymentMethodList(payments: payments));
    out.add(const SizedBox(height: 16));

    if (payments == null) {
      out.add(const LoadingView(message: 'Loading payment options…'));
      return out;
    }
    if (!payments.enabled || payments.method('card')?.enabled != true) {
      out.add(_Notice(
        icon: Icons.block,
        color: HelmTheme.mutedText,
        title: 'Payments are unavailable',
        message: payments.method('card')?.reason ?? 'Card payments are not configured on this server.',
      ));
      return out;
    }

    final intent = state.intent;
    if (payments.provider == 'local') {
      out.add(_LocalTestPanel(
        busy: state.busy || state.waiting,
        requiresAction: phase == PaymentPhase.requiresAction,
        intent: intent,
        lastEvent: state.lastTestEvent,
        onOutcome: (o) async {
          await _controller.confirmLocal(o);
          if (mounted) setState(() => _retrying = false);
        },
      ));
    } else if (payments.provider == 'stripe') {
      final webBridge = ref.watch(stripeWebBridgeFactoryProvider);
      if (webBridge != null) {
        // Web: Stripe.js Payment Element (card only), loaded on demand.
        if (intent == null) {
          out.add(const LoadingView(message: 'Preparing secure card payment…'));
        } else {
          if (phase == PaymentPhase.requiresAction) {
            out.add(const _Notice(
              icon: Icons.verified_user,
              color: HelmTheme.warning,
              title: 'Your bank needs you to confirm this payment',
              message: 'Pay again with the card below to complete authentication.',
            ));
            out.add(const SizedBox(height: 12));
          }
          out.add(WebCardPaymentForm(
            key: ValueKey('web-card-${intent.clientSecret}'),
            createBridge: webBridge,
            orderId: order.id,
            clientSecret: intent.clientSecret,
            publishableKey: intent.publishableKey ?? payments.stripePublishableKey,
            payLabel: 'Pay ${formatCents(order.totalCents)}',
            disabled: state.busy || state.waiting || phase == PaymentPhase.processing,
            onSubmitted: () async {
              if (mounted) setState(() => _retrying = false);
              await _controller.awaitServerResult();
            },
          ));
        }
      } else if (!ref.watch(stripeNativeSheetSupportedProvider)) {
        out.add(const _Notice(
          icon: Icons.web_asset_off,
          color: HelmTheme.warning,
          title: 'Card payments are not available in this version of the app',
          message: 'Use the Helm website or mobile app to pay for this order.',
        ));
      } else if (intent == null) {
        out.add(const LoadingView(message: 'Preparing secure card payment…'));
      } else {
        if (phase == PaymentPhase.requiresAction) {
          out.add(const _Notice(
            icon: Icons.verified_user,
            color: HelmTheme.warning,
            title: 'Your bank needs you to confirm this payment',
            message: 'Continue with the card payment to complete authentication.',
          ));
          out.add(const SizedBox(height: 12));
        }
        out.add(FilledButton.icon(
          onPressed: state.busy || state.waiting
              ? null
              : () => _payWithStripe(payments, intent),
          icon: const Icon(Icons.lock),
          label: Text('Pay ${formatCents(order.totalCents)}'),
        ));
      }
    } else {
      out.add(_Notice(
        icon: Icons.block,
        color: HelmTheme.mutedText,
        title: 'Payments are unavailable',
        message: 'Unknown payment provider "${payments.provider}".',
      ));
    }
    return out;
  }
}

/// Payment methods as the server reports them. Only enabled methods can be
/// chosen; Afterpay / Laybuy are listed disabled with the recorded reason.
class PaymentMethodList extends StatelessWidget {
  const PaymentMethodList({super.key, required this.payments});

  final PaymentsConfig? payments;

  static String _label(String id) => switch (id) {
        'card' => 'Credit or debit card',
        'afterpay' => 'Afterpay',
        'laybuy' => 'Laybuy',
        _ => id,
      };

  @override
  Widget build(BuildContext context) {
    final methods = payments?.methods ?? const <PaymentMethodConfig>[];
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(header: true, child: Text('Payment method', style: theme.textTheme.titleMedium)),
        const SizedBox(height: 4),
        for (final m in methods)
          Card(
            child: ListTile(
              enabled: m.enabled,
              leading: Icon(
                m.enabled ? Icons.radio_button_checked : Icons.block,
                color: m.enabled ? HelmTheme.primary : HelmTheme.mutedText,
              ),
              title: Text(_label(m.id)),
              subtitle: m.enabled ? const Text('Selected') : Text('Not available — ${m.reason ?? 'not offered'}'),
            ),
          ),
      ],
    );
  }
}

class _LocalTestPanel extends StatelessWidget {
  const _LocalTestPanel({
    required this.busy,
    required this.requiresAction,
    required this.intent,
    required this.lastEvent,
    required this.onOutcome,
  });

  final bool busy;
  final bool requiresAction;
  final PaymentIntentInfo? intent;
  final LocalConfirmResult? lastEvent;
  final ValueChanged<LocalPaymentOutcome> onOutcome;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: HelmTheme.warning.withValues(alpha: 0.08),
        border: Border.all(color: HelmTheme.warning, width: 2),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            header: true,
            child: Text('TEST MODE — no real charge',
                style: theme.textTheme.titleMedium?.copyWith(color: HelmTheme.warning, fontWeight: FontWeight.bold)),
          ),
          const SizedBox(height: 4),
          const Text(
            'This server uses the local test payment provider. No card is charged. Choose what the card does; '
            'the result goes through the same signed webhook processing as a real payment.',
          ),
          if (intent != null) ...[
            const SizedBox(height: 4),
            Text('Test intent ${intent!.paymentIntentId}', style: theme.textTheme.bodySmall),
          ],
          const SizedBox(height: 12),
          if (requiresAction) ...[
            const Text('The (simulated) bank asks you to authenticate this payment.'),
            const SizedBox(height: 8),
            FilledButton.icon(
              onPressed: busy ? null : () => onOutcome(LocalPaymentOutcome.authenticate),
              icon: const Icon(Icons.verified_user),
              label: const Text('Authenticate (test)'),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: busy ? null : () => onOutcome(LocalPaymentOutcome.decline),
              child: const Text('Fail authentication (test decline)'),
            ),
          ] else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: busy ? null : () => onOutcome(LocalPaymentOutcome.succeed),
                  icon: const Icon(Icons.check),
                  label: const Text('Simulate success'),
                ),
                OutlinedButton.icon(
                  onPressed: busy ? null : () => onOutcome(LocalPaymentOutcome.decline),
                  icon: const Icon(Icons.close),
                  label: const Text('Simulate decline'),
                ),
                OutlinedButton.icon(
                  onPressed: busy ? null : () => onOutcome(LocalPaymentOutcome.requiresAction),
                  icon: const Icon(Icons.verified_user_outlined),
                  label: const Text('Simulate authentication required'),
                ),
              ],
            ),
          if (busy) ...[
            const SizedBox(height: 12),
            const LinearProgressIndicator(),
          ],
          if (lastEvent != null) ...[
            const SizedBox(height: 8),
            Text(
              'Last test event: ${lastEvent!.eventType} (${lastEvent!.eventOutcome})',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({
    required this.icon,
    required this.color,
    required this.title,
    required this.message,
    this.action,
    this.busy = false,
    this.liveRegion = false,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String message;
  final Widget? action;
  final bool busy;
  final bool liveRegion;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: liveRegion,
      container: true,
      child: Card(
        color: tintedCardColor(color),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              busy
                  ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 3))
                  : Icon(icon, color: color),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(color: color)),
                    const SizedBox(height: 4),
                    Text(message),
                    if (action != null) ...[const SizedBox(height: 8), action!],
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

/// "Items reserved for 29:41" counting down to the server's `expires_at`.
class ReservationCountdown extends StatefulWidget {
  const ReservationCountdown({super.key, required this.expiresAt, this.onExpired});

  final DateTime expiresAt;
  final VoidCallback? onExpired;

  @override
  State<ReservationCountdown> createState() => _ReservationCountdownState();
}

class _ReservationCountdownState extends State<ReservationCountdown> {
  Timer? _timer;
  bool _fired = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {});
      if (!_fired && !widget.expiresAt.isAfter(DateTime.now())) {
        _fired = true;
        widget.onExpired?.call();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final left = widget.expiresAt.difference(DateTime.now());
    final expired = left.isNegative || left == Duration.zero;
    final mm = left.inMinutes.toString().padLeft(2, '0');
    final ss = (left.inSeconds % 60).toString().padLeft(2, '0');
    final text = expired
        ? 'The stock reservation has expired.'
        : 'Your items are reserved for $mm:$ss — pay before then.';
    return Semantics(
      label: expired ? text : 'Items reserved for ${left.inMinutes} minutes ${left.inSeconds % 60} seconds',
      child: Row(
        children: [
          Icon(Icons.timer_outlined, color: expired ? HelmTheme.error : HelmTheme.warning),
          const SizedBox(width: 8),
          Expanded(child: ExcludeSemantics(child: Text(text))),
        ],
      ),
    );
  }
}
