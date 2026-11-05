import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Compile-time client configuration, supplied with `--dart-define`.
///
/// | Define              | Purpose                                                  |
/// |---------------------|----------------------------------------------------------|
/// | `API_BASE_URL`      | Helm API base including `/api/v1`. Required in release.  |
/// | `SUPABASE_URL`      | Supabase project URL. Required.                          |
/// | `SUPABASE_ANON_KEY` | Supabase *public* anon/publishable client key. Required. |
/// | `APP_ENV`           | `development` / `staging` / `production` (labels only).  |
/// | `SENTRY_DSN`        | Optional; Sentry is initialised only when set.           |
/// | `POSTHOG_API_KEY`   | Optional public project key; PostHog only when set.      |
/// | `POSTHOG_HOST`      | Optional PostHog host (default https://us.i.posthog.com). |
/// | `MAP_TILE_URL_TEMPLATE` / `MAP_TILE_ATTRIBUTION` | Optional raster tiles.      |
///
/// Only public client values belong here: everything compiled into the app is
/// readable by anyone who downloads it. Never pass a service-role key, JWT
/// secret, Stripe secret key or similar.
@immutable
class AppConfig {
  const AppConfig({
    required this.apiBaseUrl,
    required this.supabaseUrl,
    required this.supabaseAnonKey,
    required this.appEnv,
    required this.isRelease,
    this.sentryDsn = '',
    this.posthogApiKey = '',
    this.posthogHost = defaultPosthogHost,
    this.mapTileUrlTemplate = '',
    this.mapTileAttribution = '',
  });

  /// Debug builds talk to the local reverse proxy unless told otherwise.
  static const debugDefaultApiBaseUrl = 'http://localhost:8080/api/v1';
  static const defaultPosthogHost = 'https://us.i.posthog.com';

  final String apiBaseUrl;
  final String supabaseUrl;
  final String supabaseAnonKey;
  final String appEnv;
  final bool isRelease;
  final String sentryDsn;
  final String posthogApiKey;
  final String posthogHost;
  final String mapTileUrlTemplate;
  final String mapTileAttribution;

  /// Reads the `--dart-define` values compiled into this build.
  factory AppConfig.fromEnvironment() => AppConfig.resolve(
        isRelease: kReleaseMode,
        apiBaseUrl: const String.fromEnvironment('API_BASE_URL'),
        supabaseUrl: const String.fromEnvironment('SUPABASE_URL'),
        supabaseAnonKey: const String.fromEnvironment('SUPABASE_ANON_KEY'),
        appEnv: const String.fromEnvironment('APP_ENV'),
        sentryDsn: const String.fromEnvironment('SENTRY_DSN'),
        posthogApiKey: const String.fromEnvironment('POSTHOG_API_KEY'),
        posthogHost: const String.fromEnvironment('POSTHOG_HOST'),
        mapTileUrlTemplate: const String.fromEnvironment('MAP_TILE_URL_TEMPLATE'),
        mapTileAttribution: const String.fromEnvironment('MAP_TILE_ATTRIBUTION'),
      );

  /// Applies defaults. Debug builds default the API to the local reverse proxy;
  /// release builds get no default (see [problems]).
  factory AppConfig.resolve({
    required bool isRelease,
    String apiBaseUrl = '',
    String supabaseUrl = '',
    String supabaseAnonKey = '',
    String appEnv = '',
    String sentryDsn = '',
    String posthogApiKey = '',
    String posthogHost = '',
    String mapTileUrlTemplate = '',
    String mapTileAttribution = '',
  }) {
    var api = apiBaseUrl.trim();
    if (api.isEmpty && !isRelease) api = debugDefaultApiBaseUrl;
    while (api.endsWith('/')) {
      api = api.substring(0, api.length - 1);
    }
    return AppConfig(
      apiBaseUrl: api,
      supabaseUrl: supabaseUrl.trim(),
      supabaseAnonKey: supabaseAnonKey.trim(),
      appEnv: appEnv.trim().isEmpty
          ? (isRelease ? 'production' : 'development')
          : appEnv.trim(),
      isRelease: isRelease,
      sentryDsn: sentryDsn.trim(),
      posthogApiKey: posthogApiKey.trim(),
      posthogHost:
          posthogHost.trim().isEmpty ? defaultPosthogHost : posthogHost.trim(),
      mapTileUrlTemplate: mapTileUrlTemplate.trim(),
      mapTileAttribution: mapTileAttribution.trim(),
    );
  }

  bool get sentryEnabled => sentryDsn.isNotEmpty;
  bool get posthogEnabled => posthogApiKey.isNotEmpty;


  /// Reasons this build must not start. Empty means the configuration is usable.
  List<String> problems() {
    final out = <String>[];
    final api = Uri.tryParse(apiBaseUrl);
    if (apiBaseUrl.isEmpty) {
      out.add('API_BASE_URL is not set.');
    } else if (api == null ||
        !(api.scheme == 'http' || api.scheme == 'https') ||
        api.host.isEmpty) {
      out.add('API_BASE_URL is not a valid http(s) URL: $apiBaseUrl');
    } else if (isRelease && !_localDevelopment && _isLoopback(api.host)) {
      out.add('API_BASE_URL points at ${api.host}; release builds need the '
          'public API address.');
    } else if (isRelease && !_localDevelopment && api.scheme != 'https') {
      out.add('API_BASE_URL must use https:// in release builds.');
    }
    final supa = Uri.tryParse(supabaseUrl);
    if (supabaseUrl.isEmpty) {
      out.add('SUPABASE_URL is not set.');
    } else if (supa == null ||
        !(supa.scheme == 'http' || supa.scheme == 'https') ||
        supa.host.isEmpty) {
      out.add('SUPABASE_URL is not a valid http(s) URL: $supabaseUrl');
    } else if (isRelease && !_localDevelopment && _isLoopback(supa.host)) {
      out.add('SUPABASE_URL points at ${supa.host}; release builds need the '
          'hosted Supabase project.');
    } else if (isRelease && !_localDevelopment && supa.scheme != 'https') {
      out.add('SUPABASE_URL must use https:// in release builds.');
    }
    if (supabaseAnonKey.isEmpty) {
      out.add('SUPABASE_ANON_KEY (the public anon key) is not set.');
    }
    return out;
  }

  /// A release build explicitly made for the local acceptance stack
  /// (`APP_ENV=development`, as scripts/local_stack.sh does) may use loopback
  /// addresses; every other release build must point at public hosts.
  bool get _localDevelopment => appEnv == 'development';

  static bool _isLoopback(String host) {
    final h = host.toLowerCase();
    return h == 'localhost' ||
        h.endsWith('.localhost') ||
        h == '127.0.0.1' ||
        h.startsWith('127.') ||
        h == '0.0.0.0' ||
        h == '::1' ||
        h == '[::1]';
  }
}

/// The build's configuration. Overridden in `main()` (and in tests).
final appConfigProvider = Provider<AppConfig>(
  (ref) => throw UnimplementedError('appConfigProvider must be overridden'),
);
