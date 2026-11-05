import 'package:flutter/foundation.dart';
import 'package:flutter_stripe/flutter_stripe.dart';

/// Result of a client-side card confirmation. It only says what the Stripe
/// SDK reported; the order is paid only when the server says so.
enum StripeConfirmation { submitted, canceled }

String? _initialisedKey;

/// Configures flutter_stripe with the publishable key from `/config/public`.
Future<void> ensureStripe(String publishableKey) async {
  if (_initialisedKey == publishableKey) return;
  Stripe.publishableKey = publishableKey;
  await Stripe.instance.applySettings();
  _initialisedKey = publishableKey;
}

/// Whether this build can take Stripe card payments on this platform.
///
/// Web: flutter_stripe_web 8.2.0 (the release matching flutter_stripe 14.2.0)
/// does not compile against stripe_platform_interface 14.2.0 (non-exhaustive
/// switch on `PaymentIntentsFutureUsage`), so this build has no Payment
/// Element and says so explicitly instead of offering a card form.
bool get stripeSupportedHere => !kIsWeb;

/// Mobile: presents Stripe's PaymentSheet for [clientSecret].
Future<StripeConfirmation> presentStripePaymentSheet({
  required String publishableKey,
  required String clientSecret,
}) async {
  await ensureStripe(publishableKey);
  await Stripe.instance.initPaymentSheet(
    paymentSheetParameters: SetupPaymentSheetParameters(
      paymentIntentClientSecret: clientSecret,
      merchantDisplayName: 'Helm Marine',
    ),
  );
  try {
    await Stripe.instance.presentPaymentSheet();
    return StripeConfirmation.submitted;
  } on StripeException catch (e) {
    if (e.error.code == FailureCode.Canceled) return StripeConfirmation.canceled;
    rethrow;
  }
}

/// A safe message for a Stripe SDK error (no internals).
String describeStripeError(Object error) {
  if (error is StripeException) {
    return error.error.localizedMessage ?? error.error.message ?? 'The card payment could not be completed.';
  }
  return 'The card payment could not be completed.';
}
