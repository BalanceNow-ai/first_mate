import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/config/app_config.dart';
import 'package:posthog_flutter/posthog_flutter.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

/// Product analytics and error-monitoring facade. Each backend is active only
/// when configured (`POSTHOG_API_KEY`, `SENTRY_DSN`); otherwise calls are no-ops.
/// No personal data is sent: users are identified by their opaque id only.
class Monitoring {
  const Monitoring({this.posthog = false, this.sentry = false});

  const Monitoring.disabled() : this();

  final bool posthog;
  final bool sentry;

  /// Initialises PostHog when configured. Sentry is initialised in `main()`
  /// because it wraps `runApp`.
  static Future<Monitoring> start(AppConfig config) async {
    var posthogReady = false;
    if (config.posthogEnabled) {
      try {
        final ph = PostHogConfig(config.posthogApiKey)
          ..host = config.posthogHost
          ..captureApplicationLifecycleEvents = false;
        await Posthog().setup(ph);
        posthogReady = true;
      } catch (e) {
        debugPrint('PostHog disabled: setup failed (${e.runtimeType})');
      }
    }
    return Monitoring(posthog: posthogReady, sentry: config.sentryEnabled);
  }

  Future<void> capture(String event, {Map<String, Object>? properties}) async {
    if (!posthog) return;
    try {
      await Posthog().capture(eventName: event, properties: properties);
    } catch (_) {}
  }

  Future<void> identify(String userId) async {
    if (sentry) Sentry.configureScope((scope) => scope.setUser(SentryUser(id: userId)));
    if (!posthog) return;
    try {
      await Posthog().identify(userId: userId);
    } catch (_) {}
  }

  /// Forgets the signed-in user (on sign-out).
  Future<void> resetIdentity() async {
    if (sentry) Sentry.configureScope((scope) => scope.setUser(null));
    if (!posthog) return;
    try {
      await Posthog().reset();
    } catch (_) {}
  }
}

final monitoringProvider = Provider<Monitoring>((ref) => const Monitoring.disabled());
