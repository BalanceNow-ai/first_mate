// Shared helpers for the engagement client tests (First Mate, Crew Rewards,
// home/content, admin). Fixtures are REAL server payloads captured from the
// local stack by scripts/capture_api_fixtures_pass2_engagement.py into
// test/fixtures/api/engagement/.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/app_harness.dart';
import '../../helpers/fakes.dart';

dynamic eng(String name) => fixture('engagement/$name');

Map<String, dynamic> engMap(String name) => (eng(name) as Map).cast<String, dynamic>();

List<Map<String, dynamic>> engList(String name) =>
    [for (final e in eng(name) as List) (e as Map).cast<String, dynamic>()];

/// The fixture backend plus the engagement endpoints the shell/home touch.
FakeBackend engagementBackend() {
  final backend = fixtureBackend();
  backend.json('GET /content/articles', 200, eng('content_articles'));
  backend.json('GET /helm-dash/deliveries', 200, eng('helm_dash_deliveries_empty'));
  backend.json('GET /ai/conversations', 200, eng('ai_conversations'));
  return backend;
}

/// The admin account captured by the fixture script (`role: admin`).
Map<String, dynamic> adminUser() =>
    engList('admin_users').firstWhere((u) => u['role'] == 'admin');

/// A backend + gateway for the captured admin account.
(FakeBackend, FakeAuthGateway) adminSession() {
  final backend = engagementBackend();
  final admin = adminUser();
  backend.json('POST /auth/provision', 200, admin);
  backend.json('GET /auth/me', 200, admin);
  final gateway = FakeAuthGateway(token: 'token-admin', userId: admin['id'] as String, email: admin['email'] as String);
  return (backend, gateway);
}

/// The real app, signed in, at `/`.
Future<AppHarness> engagementApp(
  WidgetTester tester, {
  FakeBackend? backend,
  FakeAuthGateway? gateway,
  Size size = const Size(1000, 1400),
}) async {
  final app = AppHarness(tester, gateway: gateway ?? fixtureGateway(), backend: backend ?? engagementBackend());
  await app.start(size: size);
  expect(app.location, '/');
  return app;
}
