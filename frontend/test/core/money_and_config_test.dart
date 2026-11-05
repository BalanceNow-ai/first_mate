import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/config/app_config.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/models/product.dart';

void main() {
  group('formatCents', () {
    test('formats integer cents without floating point', () {
      expect(formatCents(0), r'$0.00');
      expect(formatCents(5), r'$0.05');
      expect(formatCents(7490), r'$74.90');
      expect(formatCents(123456789), r'$1,234,567.89');
      expect(formatCents(-1250), r'-$12.50');
      expect(formatCents(14980, showCode: true), r'$149.80 NZD');
      expect(formatCents(1000, currency: 'AUD'), 'AUD 10.00');
    });

    test('cents fields must be integers', () {
      expect(() => centsFrom({'price_cents': 74.9}, 'price_cents'), throwsFormatException);
      expect(() => centsFrom({'price_cents': '7490'}, 'price_cents'), throwsFormatException);
      expect(optionalCentsFrom({'sale_price_cents': null}, 'sale_price_cents'), isNull);
    });
  });

  group('FitmentBadge labels', () {
    test('only verified fit / universal read as fitting', () {
      expect(FitmentBadge.labelFor(FitmentStatus.verifiedFit, 'Sea Biscuit'), 'Fits Sea Biscuit');
      expect(FitmentBadge.labelFor(FitmentStatus.universal, 'Sea Biscuit'), 'Fits Sea Biscuit');
      expect(FitmentBadge.labelFor(FitmentStatus.verifiedMismatch, 'Sea Biscuit'), 'Does not fit');
      expect(FitmentBadge.labelFor(FitmentStatus.unknown, 'Sea Biscuit'), 'Fit unknown — not verified');
    });
  });

  group('AppConfig', () {
    test('debug builds default to the local reverse proxy', () {
      final c = AppConfig.resolve(isRelease: false, supabaseUrl: 'http://localhost:54321', supabaseAnonKey: 'anon');
      expect(c.apiBaseUrl, 'http://localhost:8080/api/v1');
      expect(c.appEnv, 'development');
      expect(c.problems(), isEmpty);
    });

    test('release builds refuse a missing API_BASE_URL', () {
      final c = AppConfig.resolve(isRelease: true, supabaseUrl: 'https://x.supabase.co', supabaseAnonKey: 'anon');
      expect(c.apiBaseUrl, isEmpty);
      expect(c.problems(), contains(contains('API_BASE_URL is not set')));
    });

    test('release builds refuse localhost / 127.0.0.1 API addresses', () {
      for (final url in ['http://localhost:8000/api/v1', 'http://127.0.0.1/api/v1', 'http://0.0.0.0:80/api/v1']) {
        final c = AppConfig.resolve(
          isRelease: true,
          apiBaseUrl: url,
          supabaseUrl: 'https://x.supabase.co',
          supabaseAnonKey: 'anon',
        );
        expect(c.problems(), isNotEmpty, reason: url);
      }
    });

    test('release builds require https unless APP_ENV=development', () {
      final c = AppConfig.resolve(
        isRelease: true,
        apiBaseUrl: 'http://api.example.com/api/v1',
        supabaseUrl: 'http://x.supabase.co',
        supabaseAnonKey: 'anon',
      );
      expect(c.problems().where((p) => p.contains('https')), hasLength(2));
    });

    test('an explicit development release build (local stack) may use loopback', () {
      final dev = AppConfig.resolve(
        isRelease: true,
        appEnv: 'development',
        apiBaseUrl: 'http://localhost:18080/api/v1',
        supabaseUrl: 'http://localhost:18080',
        supabaseAnonKey: 'anon',
      );
      expect(dev.problems(), isEmpty);
      final prod = AppConfig.resolve(
        isRelease: true,
        appEnv: 'production',
        apiBaseUrl: 'http://localhost:18080/api/v1',
        supabaseUrl: 'http://localhost:18080',
        supabaseAnonKey: 'anon',
      );
      expect(prod.problems(), hasLength(2));
    });

    test('Supabase configuration is required', () {
      final c = AppConfig.resolve(isRelease: true, apiBaseUrl: 'https://api.helm.nz/api/v1');
      final problems = c.problems();
      expect(problems, contains(contains('SUPABASE_URL is not set')));
      expect(problems, contains(contains('SUPABASE_ANON_KEY')));
    });

    test('a complete release configuration passes and trailing slashes are trimmed', () {
      final c = AppConfig.resolve(
        isRelease: true,
        apiBaseUrl: 'https://api.example.invalid/api/v1/',
        supabaseUrl: 'https://example.supabase.co',
        supabaseAnonKey: 'public-anon-placeholder',
      );
      expect(c.problems(), isEmpty);
      expect(c.apiBaseUrl, 'https://api.example.invalid/api/v1');
      expect(c.appEnv, 'production');
      expect(c.sentryEnabled, isFalse);
      expect(c.posthogEnabled, isFalse);
    });

    test('monitoring initialises only when configured', () {
      final c = AppConfig.resolve(isRelease: false, sentryDsn: 'https://k@o.ingest.sentry.io/1', posthogApiKey: 'phc_x');
      expect(c.sentryEnabled, isTrue);
      expect(c.posthogEnabled, isTrue);
      expect(c.posthogHost, AppConfig.defaultPosthogHost);
    });
  });
}
