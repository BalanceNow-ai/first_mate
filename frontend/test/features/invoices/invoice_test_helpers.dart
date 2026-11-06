// Shared helpers for the invoice / moderation client tests. Fixtures are REAL
// server payloads captured from the local stack by
// scripts/capture_api_fixtures_invoices.py into test/fixtures/api/invoices/.
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/app.dart';
import 'package:helm_marine/core/router.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';

import '../../helpers/fakes.dart';

dynamic inv(String name) => fixture('invoices/$name');

Map<String, dynamic> invMap(String name) => (inv(name) as Map).cast<String, dynamic>();

List<Map<String, dynamic>> invList(String name) =>
    [for (final e in inv(name) as List) (e as Map).cast<String, dynamic>()];

/// A deep copy of a fixture map (for tests that vary one server flag).
Map<String, dynamic> copyOf(Map<String, dynamic> json) => (_deep(json) as Map).cast<String, dynamic>();

Object? _deep(Object? v) => switch (v) {
      Map() => {for (final e in v.entries) '${e.key}': _deep(e.value)},
      List() => [for (final e in v) _deep(e)],
      _ => v,
    };

/// The fixture backend signed in as the captured invoice owner.
(FakeBackend, FakeAuthGateway) ownerSession() => _session('auth_me_owner', 'token-owner');

/// The captured moderator account (`role: moderator`, granted by the CLI).
(FakeBackend, FakeAuthGateway) moderatorSession() => _session('auth_me_moderator', 'token-moderator');

(FakeBackend, FakeAuthGateway) _session(String me, String token) {
  final backend = fixtureBackend();
  final user = invMap(me);
  backend.json('POST /auth/provision', 200, user);
  backend.json('GET /auth/me', 200, user);
  backend.json('GET /orders/', 200, fixture('orders_list'));
  final gateway = FakeAuthGateway(token: token, userId: user['id'] as String, email: user['email'] as String);
  return (backend, gateway);
}

/// A PDF the fake file chooser "picks".
final pickedPdf = PickedDocument(
  name: 'harbour-invoice.pdf',
  bytes: Uint8List.fromList('%PDF-1.4 synthetic'.codeUnits),
  contentType: 'application/pdf',
);

/// The real app (router, shell, auth redirects) wired to fakes, pumped without
/// `pumpAndSettle` (progress indicators animate while polling).
class InvoiceHarness {
  InvoiceHarness(this.tester, {required this.backend, required this.gateway, List<Override> overrides = const []}) {
    container = ProviderContainer(
      overrides: [
        ...testOverrides(gateway: gateway, backend: backend),
        invoicePollIntervalProvider.overrideWithValue(Duration.zero),
        invoicePollAttemptsProvider.overrideWithValue(5),
        documentBytesFetcherProvider.overrideWithValue((url) async => Uint8List(0)),
        ...overrides,
      ],
      retry: (_, _) => null,
    );
  }

  final WidgetTester tester;
  final FakeBackend backend;
  final FakeAuthGateway gateway;
  late final ProviderContainer container;

  Future<void> start({Size size = const Size(1280, 8000)}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const HelmApp()));
    await pump();
  }

  Future<void> stop() async {
    await tester.pumpWidget(const SizedBox());
    container.dispose();
  }

  Future<void> go(String location) async {
    container.read(routerProvider).go(location);
    await pump();
  }

  String get location => container.read(routerProvider).routerDelegate.currentConfiguration.uri.toString();

  Future<void> pump([int rounds = 20]) async {
    for (var i = 0; i < rounds; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
      await tester.pump(const Duration(milliseconds: 50));
    }
  }

  Future<void> tap(Finder finder) async {
    await tester.ensureVisible(finder.first);
    await tester.pump();
    await tester.tap(finder.first);
    await pump();
  }
}
