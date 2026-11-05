import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/config/public_config.dart';

/// The server's public configuration (`GET /api/v1/config/public`), fetched
/// once at start-up (the app shell watches it) and on demand via `ref.invalidate`.
/// Features read payment methods (with the reasons unavailable ones are not
/// offered), delivery availability, AI mode, CMS mode and the Mapbox public
/// token from here rather than from compiled-in values.
final publicConfigProvider = FutureProvider<PublicConfig>((ref) {
  return ref.watch(apiServiceProvider).getPublicConfig();
});
