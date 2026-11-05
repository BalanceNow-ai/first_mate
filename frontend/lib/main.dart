import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/auth/secure_session_storage.dart';
import 'package:helm_marine/app.dart';
import 'package:helm_marine/core/auth/auth_gateway.dart';
import 'package:helm_marine/core/config/app_config.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';
import 'package:helm_marine/core/startup/startup_error_app.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

const _configHint = 'Build with --dart-define=API_BASE_URL=https://<api-host>/api/v1 '
    '--dart-define=SUPABASE_URL=https://<project>.supabase.co '
    '--dart-define=SUPABASE_ANON_KEY=<public anon key>.';

/// Keeps the web semantics tree enabled (screen readers and browser automation
/// see real labelled elements instead of a bare canvas).
SemanticsHandle? _webSemantics;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (kIsWeb) _webSemantics ??= SemanticsBinding.instance.ensureSemantics();

  final config = AppConfig.fromEnvironment();
  final problems = config.problems();
  if (problems.isNotEmpty) {
    runApp(StartupErrorApp(
      title: 'Helm is not configured',
      problems: problems,
      hint: _configHint,
    ));
    return;
  }

  // Restores the persisted session (if any) before the first frame.
  try {
    await Supabase.initialize(
      url: config.supabaseUrl,
      publishableKey: config.supabaseAnonKey,
      // Native builds keep the session in the platform keystore, not plain prefs.
      authOptions: SecureSessionStorage.applies
          ? FlutterAuthClientOptions(localStorage: SecureSessionStorage())
          : const FlutterAuthClientOptions(),
    );
  } catch (e) {
    runApp(StartupErrorApp(
      title: 'Sign-in could not start',
      problems: ['Supabase failed to initialise (${e.runtimeType}).'],
      hint: 'Check SUPABASE_URL / SUPABASE_ANON_KEY and your connection, then reload.',
    ));
    return;
  }

  final monitoring = await Monitoring.start(config);

  void run() {
    runApp(ProviderScope(
      // Failures are shown with a "Try again" action instead of silent retries.
      retry: (retryCount, error) => null,
      overrides: [
        appConfigProvider.overrideWithValue(config),
        authGatewayProvider.overrideWithValue(SupabaseAuthGateway(Supabase.instance.client.auth)),
        monitoringProvider.overrideWithValue(monitoring),
      ],
      child: const HelmApp(),
    ));
  }

  if (config.sentryEnabled) {
    await SentryFlutter.init(
      (options) {
        options.dsn = config.sentryDsn;
        options.environment = config.appEnv;
        options.tracesSampleRate = 0.1;
        options.sendDefaultPii = false;
      },
      appRunner: run,
    );
  } else {
    run();
  }
}
