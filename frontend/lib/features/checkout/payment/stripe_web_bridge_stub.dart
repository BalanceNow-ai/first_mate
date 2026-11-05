import 'package:helm_marine/features/checkout/payment/stripe_web_bridge.dart';

/// Non-web builds use flutter_stripe's PaymentSheet; there is no web bridge.
const StripeWebBridgeFactory? stripeWebBridgeFactory = null;

StripeRedirectReturn? takeStripeRedirectReturn() => null;
