import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';
import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';
import 'package:web/web.dart' as web;

/// Stripe.js must be loaded from Stripe's own origin (PCI): never bundled,
/// never with a key embedded. Injected only when a Stripe card payment is shown.
const String stripeJsUrl = 'https://js.stripe.com/v3/';
const String _scriptId = 'helm-stripe-js';
const String _viewType = 'helm-stripe-payment-element';
const String _regionLabel = 'Card details, secured by Stripe';
const Duration _scriptTimeout = Duration(seconds: 20);
const Duration _hostTimeout = Duration(seconds: 10);
const Duration _readyTimeout = Duration(seconds: 30);

const StripeWebBridgeFactory stripeWebBridgeFactory = StripeJsBridge.new;

// ------------------------------------------------------------------ Stripe.js

@JS('Stripe')
external _StripeJs _createStripe(String publishableKey);

extension type _StripeJs._(JSObject _) implements JSObject {
  external _Elements elements(JSObject options);
  external JSPromise<_ConfirmResult> confirmPayment(JSObject options);
}

extension type _Elements._(JSObject _) implements JSObject {
  external _PaymentElement create(String type, JSObject options);
}

extension type _PaymentElement._(JSObject _) implements JSObject {
  external void mount(web.HTMLElement target);
  external void destroy();
  external void on(String event, JSFunction handler);
}

extension type _ConfirmResult._(JSObject _) implements JSObject {
  external _StripeError? get error;
  external _PaymentIntent? get paymentIntent;
}

extension type _StripeError._(JSObject _) implements JSObject {
  external String? get type;
  external String? get code;
  external String? get message;
  @JS('decline_code')
  external String? get declineCode;
}

extension type _PaymentIntent._(JSObject _) implements JSObject {
  external String? get status;
}

extension type _LoadErrorEvent._(JSObject _) implements JSObject {
  external _StripeError? get error;
}

bool get _stripeLoaded => globalContext.has('Stripe');

Future<void>? _loading;
final Map<String, _StripeJs> _instances = {};

/// Loads Stripe.js once per page. A failed attempt is forgotten so the user
/// can retry (the stale script tag is replaced).
Future<void> _loadStripeJs() {
  if (_stripeLoaded) return Future.value();
  return _loading ??= _injectScript().whenComplete(() => _loading = null);
}

Future<void> _injectScript() {
  web.document.getElementById(_scriptId)?.remove();
  final script = web.HTMLScriptElement()
    ..id = _scriptId
    ..src = stripeJsUrl
    ..async = true;
  final done = Completer<void>();
  void fail(String message) {
    script.remove();
    if (!done.isCompleted) done.completeError(StripeWebFailure(message));
  }

  script.addEventListener(
    'load',
    ((web.Event _) {
      if (_stripeLoaded) {
        if (!done.isCompleted) done.complete();
      } else {
        fail('Stripe.js loaded but did not initialise.');
      }
    }).toJS,
  );
  script.addEventListener(
    'error',
    ((web.Event _) => fail('Stripe.js could not be loaded (offline, blocked or not allowed by the page policy).')).toJS,
  );
  (web.document.head ?? web.document.body)!.append(script);
  return done.future.timeout(_scriptTimeout, onTimeout: () {
    script.remove();
    throw const StripeWebFailure('Stripe.js took too long to load.');
  });
}

_StripeJs _stripeFor(String publishableKey) => _instances[publishableKey] ??= _createStripe(publishableKey);

// --------------------------------------------------------------- host views

final Map<int, web.HTMLDivElement> _hosts = {};
bool _factoryRegistered = false;

void _ensureViewFactory() {
  if (_factoryRegistered) return;
  ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
    final outer = web.HTMLDivElement()
      ..id = 'helm-stripe-host-$viewId'
      ..setAttribute('role', 'group')
      ..setAttribute('aria-label', _regionLabel);
    outer.style
      ..width = '100%'
      ..height = '100%'
      ..overflowY = 'auto'
      ..boxSizing = 'border-box'
      ..padding = '4px 2px';
    final target = web.HTMLDivElement()..className = 'helm-stripe-payment-element';
    target.style.width = '100%';
    outer.append(target);
    _hosts[viewId] = target;
    return outer;
  });
  _factoryRegistered = true;
}

Future<web.HTMLDivElement> _connectedHost(int viewId) async {
  final deadline = DateTime.now().add(_hostTimeout);
  while (true) {
    final host = _hosts[viewId];
    if (host != null && host.isConnected) return host;
    if (DateTime.now().isAfter(deadline)) {
      throw const StripeWebFailure('The secure card form could not be placed on the page.');
    }
    await Future<void>.delayed(const Duration(milliseconds: 30));
  }
}

String _messageOf(Object error) {
  if (error is StripeWebFailure) return error.message;
  return 'The secure card form could not be loaded.';
}

// ------------------------------------------------------------------- bridge

/// [StripeWebBridge] over Stripe.js and the Payment Element.
class StripeJsBridge implements StripeWebBridge {
  StripeJsBridge();

  _StripeJs? _stripe;
  _Elements? _elements;
  _PaymentElement? _element;
  web.ResizeObserver? _observer;
  int? _viewId;
  bool _disposed = false;

  @override
  Future<void> loadStripeJs() => _loadStripeJs();

  @override
  Widget buildHost({required ValueChanged<int> onCreated}) {
    _ensureViewFactory();
    return HtmlElementView(viewType: _viewType, onPlatformViewCreated: onCreated);
  }

  @override
  Future<void> mount({
    required int viewId,
    required String publishableKey,
    required String clientSecret,
    ValueChanged<double>? onResize,
  }) async {
    _teardown();
    _viewId = viewId;
    final host = await _connectedHost(viewId);
    if (_disposed) return;
    final ready = Completer<void>();
    try {
      final stripe = _stripeFor(publishableKey);
      final elements = stripe.elements({
        'clientSecret': clientSecret,
        'appearance': {
          'theme': 'stripe',
          'variables': {
            'colorPrimary': '#1A6B9A',
            'colorDanger': '#C53030',
            'borderRadius': '8px',
            'fontFamily': 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          },
        },
      }.jsify()! as JSObject);
      final element = elements.create('payment', {
        'layout': 'tabs',
        'paymentMethodOrder': ['card'],
      }.jsify()! as JSObject);
      element.on('ready', ((JSAny? _) {
        if (!ready.isCompleted) ready.complete();
      }).toJS);
      element.on('loaderror', ((_LoadErrorEvent? e) {
        if (!ready.isCompleted) {
          ready.completeError(StripeWebFailure(
              e?.error?.message ?? 'Stripe could not load the card form for this payment.'));
        }
      }).toJS);
      _stripe = stripe;
      _elements = elements;
      _element = element;
      element.mount(host);
      if (onResize != null) {
        final observer = web.ResizeObserver(((JSArray<web.ResizeObserverEntry> entries, web.ResizeObserver _) {
          final list = entries.toDart;
          if (list.isNotEmpty && !_disposed) onResize(list.last.contentRect.height);
        }).toJS);
        observer.observe(host);
        _observer = observer;
      }
    } catch (e) {
      _teardown();
      throw StripeWebFailure(_messageOf(e));
    }
    try {
      await ready.future.timeout(_readyTimeout,
          onTimeout: () => throw const StripeWebFailure('The secure card form took too long to load.'));
    } catch (e) {
      _teardown();
      throw StripeWebFailure(_messageOf(e));
    }
  }

  @override
  Future<StripeWebConfirmResult> confirm({required String returnUrl}) async {
    final stripe = _stripe;
    final elements = _elements;
    if (stripe == null || elements == null) {
      return const StripeWebConfirmError(message: 'The card form is not ready yet.');
    }
    final options = JSObject()
      ..setProperty('elements'.toJS, elements)
      ..setProperty('redirect'.toJS, 'if_required'.toJS)
      ..setProperty('confirmParams'.toJS, {'return_url': returnUrl}.jsify());
    final result = await stripe.confirmPayment(options).toDart;
    final error = result.error;
    if (error != null) {
      return StripeWebConfirmError(
        message: error.message ?? 'The card payment could not be completed.',
        type: error.type,
        code: error.code,
        declineCode: error.declineCode,
      );
    }
    return StripeWebConfirmSubmitted(status: result.paymentIntent?.status);
  }

  @override
  String returnUrlFor(String orderId) {
    final location = web.window.location;
    return '${location.origin}${location.pathname}#/orders/${Uri.encodeComponent(orderId)}';
  }

  void _teardown() {
    _observer?.disconnect();
    _observer = null;
    try {
      _element?.destroy();
    } catch (_) {
      // Already gone with its host element.
    }
    _element = null;
    _elements = null;
  }

  @override
  void dispose() {
    _disposed = true;
    _teardown();
    final id = _viewId;
    if (id != null) _hosts.remove(id);
  }
}

// ------------------------------------------------------------ redirect return

bool _redirectTaken = false;

/// Stripe appends `payment_intent`, `payment_intent_client_secret` and
/// `redirect_status` to `return_url`. Read them once and remove them from the
/// address bar (the client secret should not linger in history).
StripeRedirectReturn? takeStripeRedirectReturn() {
  if (_redirectTaken) return null;
  _redirectTaken = true;
  final uri = Uri.base;
  final pi = uri.queryParameters['payment_intent'];
  if (pi == null || pi.isEmpty) return null;
  const stripeParams = {'payment_intent', 'payment_intent_client_secret', 'redirect_status'};
  final kept = {
    for (final e in uri.queryParameters.entries)
      if (!stripeParams.contains(e.key)) e.key: e.value,
  };
  final cleaned = '${uri.origin}${uri.path}'
      '${kept.isEmpty ? '' : '?${Uri(queryParameters: kept).query}'}'
      '${uri.hasFragment ? '#${uri.fragment}' : ''}';
  try {
    web.window.history.replaceState(web.window.history.state, '', cleaned);
  } catch (_) {
    // Cosmetic only.
  }
  return StripeRedirectReturn(paymentIntentId: pi, redirectStatus: uri.queryParameters['redirect_status']);
}
