import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:posthog_flutter/posthog_flutter.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:helm_marine/app.dart';

/// PostHog analytics instance accessible throughout the app.
final posthog = Posthog();

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Sentry DSN — empty string disables Sentry in development
  const sentryDsn = String.fromEnvironment('SENTRY_DSN', defaultValue: '');

  if (sentryDsn.isNotEmpty) {
    await SentryFlutter.init(
      (options) {
        options.dsn = sentryDsn;
        options.tracesSampleRate = 0.1;
        options.environment =
            const String.fromEnvironment('APP_ENV', defaultValue: 'development');
      },
      appRunner: () => _initAndRun(),
    );
  } else {
    _initAndRun();
  }
}

void _initAndRun() {
  // PostHog initialisation — API key from environment
  const posthogApiKey =
      String.fromEnvironment('POSTHOG_API_KEY', defaultValue: '');
  if (posthogApiKey.isNotEmpty) {
    Posthog().setup(
      PostHogConfig(posthogApiKey)..host = 'https://app.posthog.com',
    );
  }

  runApp(const ProviderScope(child: HelmApp()));
}
