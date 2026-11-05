import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/features/checkout/payment/payment_controller.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';
import 'package:helm_marine/features/checkout/payment/web_card_payment_controller.dart';

import '../../helpers/fakes.dart';
import '../orders/commerce_harness.dart';

const _pk = 'pk_test_fake_publishable_key';
const _pi = 'pi_3FakeStripeIntent';
const _secret = '${_pi}_secret_fake';

/// A scripted stand-in for Stripe.js + the Payment Element. Outcomes are
/// queued per call; an empty queue means success.
class FakeStripeBridge implements StripeWebBridge {
  final loadOutcomes = <Object?>[];
  final mountOutcomes = <Object?>[];
  final confirmOutcomes = <Object>[];

  int loadCalls = 0;
  final mounts = <({int viewId, String publishableKey, String clientSecret})>[];
  final confirmReturnUrls = <String>[];
  int disposeCalls = 0;
  int _nextViewId = 1;

  /// When set, `confirm` waits for it (to observe the confirming phase).
  Completer<void>? confirmGate;

  @override
  Future<void> loadStripeJs() async {
    loadCalls++;
    final outcome = loadOutcomes.isEmpty ? null : loadOutcomes.removeAt(0);
    if (outcome != null) throw outcome;
  }

  @override
  Widget buildHost({required ValueChanged<int> onCreated}) =>
      _FakeHost(allocate: () => _nextViewId++, onCreated: onCreated);

  @override
  Future<void> mount({
    required int viewId,
    required String publishableKey,
    required String clientSecret,
    ValueChanged<double>? onResize,
  }) async {
    mounts.add((viewId: viewId, publishableKey: publishableKey, clientSecret: clientSecret));
    final outcome = mountOutcomes.isEmpty ? null : mountOutcomes.removeAt(0);
    if (outcome != null) throw outcome;
    onResize?.call(240);
  }

  @override
  Future<StripeWebConfirmResult> confirm({required String returnUrl}) async {
    confirmReturnUrls.add(returnUrl);
    await confirmGate?.future;
    final outcome = confirmOutcomes.isEmpty ? const StripeWebConfirmSubmitted(status: 'succeeded') : confirmOutcomes.removeAt(0);
    if (outcome is StripeWebConfirmResult) return outcome;
    throw outcome;
  }

  @override
  String returnUrlFor(String orderId) => 'https://helm.example/#/orders/$orderId';

  @override
  void dispose() => disposeCalls++;
}

class _FakeHost extends StatefulWidget {
  const _FakeHost({required this.allocate, required this.onCreated});

  final int Function() allocate;
  final ValueChanged<int> onCreated;

  @override
  State<_FakeHost> createState() => _FakeHostState();
}

class _FakeHostState extends State<_FakeHost> {
  late final int id = widget.allocate();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => widget.onCreated(id));
  }

  @override
  Widget build(BuildContext context) => const ColoredBox(color: Colors.white, child: Text('[stripe payment element]'));
}

const _decline = StripeWebConfirmError(
  message: 'Your card was declined.',
  type: 'card_error',
  code: 'card_declined',
  declineCode: 'generic_decline',
);

WebCardPaymentController controllerFor(
  FakeStripeBridge bridge, {
  String? publishableKey = _pk,
  Future<void> Function()? onSubmitted,
}) =>
    WebCardPaymentController(
      bridge: bridge,
      orderId: 'order-1',
      clientSecret: _secret,
      publishableKey: publishableKey,
      onSubmitted: onSubmitted ?? () async {},
    );

Map<String, dynamic> stripeIntent(String orderId) => {
      ...fixtureMap('payment_intent_local'),
      'order_id': orderId,
      'provider': 'stripe',
      'payment_intent_id': _pi,
      'client_secret': _secret,
      'publishable_key': _pk,
      'test_mode': false,
    };

Map<String, dynamic> stripeConfig() {
  final config = fixtureMap('config_public_helm_dash');
  return {
    ...config,
    'payments': {
      ...(config['payments'] as Map).cast<String, dynamic>(),
      'provider': 'stripe',
      'stripe_publishable_key': _pk,
      'local_test_mode': false,
    },
  };
}

void main() {
  group('WebCardPaymentController', () {
    test('Stripe.js load failure is reported as unavailable, never as a payment result; retry reloads', () async {
      final bridge = FakeStripeBridge()..loadOutcomes.add(const StripeWebFailure('Stripe.js could not be loaded.'));
      var submitted = 0;
      final c = controllerFor(bridge, onSubmitted: () async => submitted++);
      addTearDown(c.dispose);

      await c.start();
      expect(c.phase, WebCardPhase.unavailable);
      expect(c.unavailableReason, 'Stripe.js could not be loaded.');
      expect(c.showsHost, isFalse);
      expect(c.canPay, isFalse);
      await c.pay();
      expect(bridge.confirmReturnUrls, isEmpty, reason: 'cannot confirm without the card form');

      await c.retry();
      expect(bridge.loadCalls, 2);
      expect(c.phase, WebCardPhase.awaitingHost);
      expect(c.showsHost, isTrue);
      expect(submitted, 0);
    });

    test('no publishable key: unavailable without loading Stripe.js', () async {
      final bridge = FakeStripeBridge();
      final c = controllerFor(bridge, publishableKey: null);
      addTearDown(c.dispose);
      await c.start();
      expect(c.phase, WebCardPhase.unavailable);
      expect(c.unavailableReason, contains('publishable key'));
      expect(bridge.loadCalls, 0);
    });

    test('mount: the Payment Element is mounted once into the host view with the intent\'s secret', () async {
      final bridge = FakeStripeBridge();
      final c = controllerFor(bridge);
      addTearDown(c.dispose);
      await c.start();
      expect(c.phase, WebCardPhase.awaitingHost);
      await c.attachHost(7);
      expect(c.phase, WebCardPhase.ready);
      expect(c.canPay, isTrue);
      expect(bridge.mounts.single, (viewId: 7, publishableKey: _pk, clientSecret: _secret));
      expect(c.height, 252, reason: 'sized from the element (240) plus padding');
      await c.attachHost(7);
      expect(bridge.mounts, hasLength(1), reason: 'the same host is not mounted twice');
    });

    test('mount failure → unavailable → retry remounts into the new host', () async {
      final bridge = FakeStripeBridge()..mountOutcomes.add(const StripeWebFailure('Invalid API key.'));
      final c = controllerFor(bridge);
      addTearDown(c.dispose);
      await c.start();
      await c.attachHost(1);
      expect(c.phase, WebCardPhase.unavailable);
      expect(c.unavailableReason, 'Invalid API key.');
      await c.retry();
      await c.attachHost(2);
      expect(c.phase, WebCardPhase.ready);
      expect(bridge.mounts.map((m) => m.viewId), [1, 2]);
    });

    test('confirm error (decline) → message shown, form stays mounted → retry confirms the SAME intent', () async {
      final bridge = FakeStripeBridge()..confirmOutcomes.add(_decline);
      var submitted = 0;
      final c = controllerFor(bridge, onSubmitted: () async => submitted++);
      addTearDown(c.dispose);
      await c.start();
      await c.attachHost(1);

      await c.pay();
      expect(c.phase, WebCardPhase.ready);
      expect(c.cardError, 'Your card was declined.');
      expect(submitted, 0, reason: 'a Stripe error is never treated as submitted');

      await c.pay();
      expect(c.cardError, isNull);
      expect(submitted, 1);
      expect(bridge.mounts, hasLength(1), reason: 'no new intent or element for the retry');
      expect(bridge.mounts.single.clientSecret, _secret);
      expect(bridge.confirmReturnUrls, ['https://helm.example/#/orders/order-1', 'https://helm.example/#/orders/order-1']);
    });

    test('a thrown confirm is an error to retry, not a success', () async {
      final bridge = FakeStripeBridge()..confirmOutcomes.add(StateError('network'));
      var submitted = 0;
      final c = controllerFor(bridge, onSubmitted: () async => submitted++);
      addTearDown(c.dispose);
      await c.start();
      await c.attachHost(1);
      await c.pay();
      expect(c.phase, WebCardPhase.ready);
      expect(c.cardError, contains('could not be completed'));
      expect(submitted, 0);
    });

    test('confirm success → submitted while the server is polled; no double confirm meanwhile', () async {
      final bridge = FakeStripeBridge()..confirmGate = Completer<void>();
      final polling = Completer<void>();
      var submitted = 0;
      final c = controllerFor(bridge, onSubmitted: () {
        submitted++;
        return polling.future;
      });
      addTearDown(c.dispose);
      await c.start();
      await c.attachHost(1);

      final paying = c.pay();
      await Future<void>.delayed(Duration.zero);
      expect(c.phase, WebCardPhase.confirming);
      expect(c.canPay, isFalse);
      bridge.confirmGate!.complete();
      await Future<void>.delayed(Duration.zero);
      expect(c.phase, WebCardPhase.submitted);
      expect(submitted, 1);
      await c.pay();
      expect(bridge.confirmReturnUrls, hasLength(1), reason: 'Pay is disabled while the server is polled');

      polling.complete();
      await paying;
      expect(c.phase, WebCardPhase.ready, reason: 'the panel shows the server\'s verdict; the form can retry');
    });

    test('dispose destroys the element', () async {
      final bridge = FakeStripeBridge();
      final c = controllerFor(bridge);
      await c.start();
      await c.attachHost(1);
      c.dispose();
      expect(bridge.disposeCalls, 1);
    });
  });

  group('with the payment controller (server is the only source of "paid")', () {
    late FakeBackend backend;
    late String orderId;
    late Map<String, dynamic> current;

    Future<ProviderContainer> container() async {
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

    setUp(() {
      backend = fixtureBackend();
      current = fixtureMap('order_checkout_created');
      orderId = current['id'] as String;
      backend.on('GET /orders/$orderId', (_) => FakeResponse(200, current));
      backend.json('POST /payments/orders/$orderId/intent', 200, stripeIntent(orderId));
    });

    test('Stripe accepted the confirmation but the server has not confirmed: not paid', () async {
      final c = await container();
      final provider = paymentControllerProvider(orderId);
      final sub = c.listen(provider, (_, _) {});
      addTearDown(sub.close);
      await until(() => c.read(provider).intent != null);
      expect(c.read(provider).intent!.provider, 'stripe');

      final bridge = FakeStripeBridge();
      final web = WebCardPaymentController(
        bridge: bridge,
        orderId: orderId,
        clientSecret: c.read(provider).intent!.clientSecret,
        publishableKey: c.read(provider).intent!.publishableKey,
        onSubmitted: c.read(provider.notifier).awaitServerResult,
      );
      addTearDown(web.dispose);
      await web.start();
      await web.attachHost(1);
      await web.pay();

      expect(c.read(provider).phase, PaymentPhase.ready);
      expect(c.read(provider).waitTimedOut, isTrue);
      expect(c.read(provider).order!.isPaid, isFalse);
      final mutating = backend.requests.where((r) => r.method != 'GET').map((r) => r.path).toSet();
      expect(mutating, {'/auth/provision', '/payments/orders/$orderId/intent'},
          reason: 'the client never reports a payment result to the server');

      // The verified webhook lands: only now is the order paid.
      current = fixtureMap('order_paid');
      await web.pay();
      expect(c.read(provider).phase, PaymentPhase.paid);
    });

    test('decline → server reports failed → retry with the same intent → server paid', () async {
      final c = await container();
      final provider = paymentControllerProvider(orderId);
      final sub = c.listen(provider, (_, _) {});
      addTearDown(sub.close);
      await until(() => c.read(provider).intent != null);
      final bridge = FakeStripeBridge()..confirmOutcomes.add(_decline);
      final web = WebCardPaymentController(
        bridge: bridge,
        orderId: orderId,
        clientSecret: _secret,
        publishableKey: _pk,
        onSubmitted: c.read(provider.notifier).awaitServerResult,
      );
      addTearDown(web.dispose);
      await web.start();
      await web.attachHost(1);
      await web.pay();
      expect(web.cardError, 'Your card was declined.');
      expect(c.read(provider).phase, PaymentPhase.ready);

      current = fixtureMap('order_paid');
      await web.pay();
      expect(c.read(provider).phase, PaymentPhase.paid);
      expect(backend.calls('POST /payments/orders/$orderId/intent'), hasLength(1));
      expect(bridge.mounts.single.clientSecret, _secret);
    });
  });

  group('payment panel on web (fake Stripe.js)', () {
    late FakeBackend backend;
    late FakeStripeBridge bridge;
    late String orderId;
    late Map<String, dynamic> current;

    CommerceHarness harness(WidgetTester tester) => CommerceHarness(
          tester,
          backend: backend,
          overrides: [
            stripeWebBridgeFactoryProvider.overrideWithValue(() => bridge),
            paymentPollIntervalProvider.overrideWithValue(Duration.zero),
            paymentPollAttemptsProvider.overrideWithValue(2),
          ],
        );

    setUp(() {
      bridge = FakeStripeBridge();
      backend = fixtureBackend();
      backend.json('GET /config/public', 200, stripeConfig());
      current = fixtureMap('order_checkout_created');
      orderId = current['id'] as String;
      backend.on('GET /orders/$orderId', (_) => FakeResponse(200, current));
      backend.json('POST /payments/orders/$orderId/intent', 200, stripeIntent(orderId));
    });

    testWidgets('load failure → explicit unavailable state → retry → card form; card only', (tester) async {
      bridge.loadOutcomes.add(const StripeWebFailure('Stripe.js could not be loaded (offline, blocked or not allowed by the page policy).'));
      final app = harness(tester);
      await app.start();
      app.go('/orders/$orderId/pay');
      await app.pump();

      expect(find.text('Card payments are unavailable right now'), findsOneWidget);
      expect(find.textContaining('Stripe.js could not be loaded'), findsOneWidget);
      expect(find.text('Payment confirmed'), findsNothing);
      expect(find.text('[stripe payment element]'), findsNothing);
      expect(find.textContaining('Card payments on web are not available'), findsNothing);
      // Afterpay / Laybuy stay disabled with the server's reasons.
      expect(find.textContaining('Not available — Afterpay is not offered'), findsOneWidget);
      expect(find.textContaining('Not available — Laybuy is not offered'), findsOneWidget);

      await app.tap(find.text('Try again'));
      expect(bridge.loadCalls, 2);
      expect(find.text('[stripe payment element]'), findsOneWidget);
      expect(bridge.mounts.single.clientSecret, _secret);
      expect(find.bySemanticsLabel(RegExp('^Card details, secured by Stripe')), findsOneWidget);
      expect(find.text('Stripe test mode — use a Stripe test card; no real charge.'), findsOneWidget);
      final pay = find.widgetWithText(FilledButton, r'Pay $123.80');
      expect(tester.widget<FilledButton>(pay).onPressed, isNotNull);
      await app.stop();
    });

    testWidgets('decline is shown and retried with the same intent; paid only when the server says so',
        (tester) async {
      bridge.confirmOutcomes.add(_decline);
      final app = harness(tester);
      await app.start();
      app.go('/orders/$orderId/pay');
      await app.pump();

      final pay = find.widgetWithText(FilledButton, r'Pay $123.80');
      await app.tap(pay);
      expect(find.textContaining('Your card was declined.'), findsOneWidget);
      expect(find.text('Payment confirmed'), findsNothing);
      expect(find.text('[stripe payment element]'), findsOneWidget);

      // Stripe accepts the retry, but no webhook has been applied yet.
      await app.tap(pay);
      expect(find.text('No confirmation yet'), findsOneWidget);
      expect(find.text('Payment confirmed'), findsNothing);

      // The verified webhook marks the order paid; the next confirmation's poll sees it.
      current = fixtureMap('order_paid');
      await app.tap(find.text('Check again'));
      expect(find.text('Payment confirmed'), findsOneWidget);
      expect(bridge.mounts, hasLength(1));
      expect(bridge.confirmReturnUrls, hasLength(2));
      expect(backend.calls('POST /payments/orders/$orderId/intent'), hasLength(1));
      expect(bridge.disposeCalls, 1, reason: 'the Payment Element is destroyed when the form goes away');
      await app.stop();
    });

    testWidgets('3-D Secure redirect return to /orders/<id>: the order screen polls the server', (tester) async {
      var gets = 0;
      backend.on('GET /orders/$orderId', (_) {
        gets++;
        // The webhook is applied while the customer was away at the bank.
        return FakeResponse(200, gets >= 2 ? fixtureMap('order_paid') : current);
      });
      var reads = 0;
      final app = CommerceHarness(
        tester,
        backend: backend,
        overrides: [
          stripeWebBridgeFactoryProvider.overrideWithValue(() => bridge),
          stripeRedirectReturnReaderProvider.overrideWithValue(() {
            reads++;
            return reads == 1
                ? StripeRedirectReturn(paymentIntentId: fixtureMap('order_paid')['payment_intent_id'] as String,
                    redirectStatus: 'succeeded')
                : null;
          }),
          paymentPollIntervalProvider.overrideWithValue(Duration.zero),
          paymentPollAttemptsProvider.overrideWithValue(3),
        ],
      );
      await app.start();
      app.go('/orders/$orderId');
      await app.pump();
      expect(gets, greaterThanOrEqualTo(2));
      expect(find.text('Awaiting payment'), findsNothing);
      expect(find.text('Confirming your payment'), findsNothing);
      expect(bridge.confirmReturnUrls, isEmpty, reason: 'nothing is confirmed client-side on return');
      await app.stop();
    });
  });
}
