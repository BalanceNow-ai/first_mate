import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/payment.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';

import '../../helpers/fakes.dart';

/// A backend that serves the captured order in whatever state the captured
/// local-provider events left it (never set by the client).
class PaymentBackend {
  PaymentBackend() {
    backend.on('GET /orders/$orderId', (_) => FakeResponse(200, current));
    backend.on('POST /payments/orders/$orderId/intent', (_) => FakeResponse(200, fixture('payment_intent_local')));
    backend.on('POST /payments/local/$pi/confirm', (r) {
      final outcome = (r.body as Map)['outcome'];
      current = switch (outcome) {
        'decline' => fixtureMap('order_payment_failed'),
        'requires_action' => fixtureMap('order_requires_action'),
        _ => fixtureMap('order_paid'),
      };
      return FakeResponse(200, fixture(switch (outcome) {
        'decline' => 'payment_local_decline',
        'requires_action' => 'payment_local_requires_action',
        'authenticate' => 'payment_local_authenticate',
        _ => 'payment_local_authenticate',
      }));
    });
    backend.on('POST /orders/$orderId/cancel', (_) {
      current = {...fixtureMap('order_cancelled'), 'id': orderId};
      return FakeResponse(200, current);
    });
  }

  final backend = fixtureBackend();
  final orderId = fixtureMap('order_checkout_created')['id'] as String;
  final pi = fixtureMap('payment_intent_local')['payment_intent_id'] as String;
  Map<String, dynamic> current = fixtureMap('order_checkout_created');
}

Future<ProviderContainer> container(FakeBackend backend) async {
  final c = ProviderContainer(
    overrides: [
      ...testOverrides(gateway: fixtureGateway(), backend: backend),
      paymentPollIntervalProvider.overrideWithValue(Duration.zero),
      paymentPollAttemptsProvider.overrideWithValue(3),
    ],
    retry: (_, _) => null,
  );
  addTearDown(c.dispose);
  c.read(authControllerProvider);
  await until(() => c.read(authControllerProvider).isSignedIn);
  return c;
}

void main() {
  test('decline → retry (same intent) → success: the order is paid only per the server', () async {
    final p = PaymentBackend();
    final c = await container(p.backend);
    final provider = paymentControllerProvider(p.orderId);
    final sub = c.listen(provider, (_, _) {});
    addTearDown(sub.close);
    await until(() => c.read(provider).intent != null);
    expect(c.read(provider).phase, PaymentPhase.ready);
    expect(c.read(provider).intent!.testMode, isTrue);

    await c.read(provider.notifier).confirmLocal(LocalPaymentOutcome.decline);
    expect(c.read(provider).phase, PaymentPhase.failed);
    expect(c.read(provider).order!.canRetryPayment, isTrue);

    await c.read(provider.notifier).retry();
    expect(p.backend.calls('POST /payments/orders/${p.orderId}/intent'), hasLength(2));
    expect(c.read(provider).intent!.paymentIntentId, p.pi, reason: 'retry reuses the intent');

    await c.read(provider.notifier).confirmLocal(LocalPaymentOutcome.succeed);
    expect(c.read(provider).phase, PaymentPhase.paid);

    // The client only ever confirms the test intent and re-reads the order.
    final mutating = p.backend.requests.where((r) => r.method != 'GET').map((r) => r.path).toSet();
    expect(mutating, {
      '/auth/provision',
      '/payments/orders/${p.orderId}/intent',
      '/payments/local/${p.pi}/confirm',
    });
    expect(p.backend.calls('GET /orders/${p.orderId}').length, greaterThanOrEqualTo(3));
  });

  test('requires_action → authenticate', () async {
    final p = PaymentBackend();
    final c = await container(p.backend);
    final provider = paymentControllerProvider(p.orderId);
    final sub = c.listen(provider, (_, _) {});
    addTearDown(sub.close);
    await until(() => c.read(provider).intent != null);
    await c.read(provider.notifier).confirmLocal(LocalPaymentOutcome.requiresAction);
    expect(c.read(provider).phase, PaymentPhase.requiresAction);
    await c.read(provider.notifier).confirmLocal(LocalPaymentOutcome.authenticate);
    expect(c.read(provider).phase, PaymentPhase.paid);
    final outcomes = [
      for (final r in p.backend.calls('POST /payments/local/${p.pi}/confirm')) (r.body as Map)['outcome'],
    ];
    expect(outcomes, ['requires_action', 'authenticate']);
  });

  test('cancel returns the order to cancelled', () async {
    final p = PaymentBackend();
    final c = await container(p.backend);
    final provider = paymentControllerProvider(p.orderId);
    final sub = c.listen(provider, (_, _) {});
    addTearDown(sub.close);
    await until(() => c.read(provider).order != null);
    expect(await c.read(provider.notifier).cancel(), isTrue);
    expect(c.read(provider).phase, PaymentPhase.cancelled);
  });

  test('a provider that never confirms is reported, not assumed paid', () async {
    final p = PaymentBackend();
    final c = await container(p.backend);
    final provider = paymentControllerProvider(p.orderId);
    final sub = c.listen(provider, (_, _) {});
    addTearDown(sub.close);
    await until(() => c.read(provider).order != null);
    await c.read(provider.notifier).awaitServerResult();
    expect(c.read(provider).phase, PaymentPhase.ready);
    expect(c.read(provider).waitTimedOut, isTrue);
  });

  test('errors from the intent endpoint are explained', () {
    expect(
      paymentErrorText(Exception('x')),
      isNotEmpty,
    );
  });
}
