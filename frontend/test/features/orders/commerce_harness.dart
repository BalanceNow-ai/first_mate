import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/app.dart';
import 'package:helm_marine/core/router.dart';

import '../../helpers/fakes.dart';

/// The real app wired to fakes, for screens with live timers (countdowns,
/// polling) where `pumpAndSettle` would never settle.
class CommerceHarness {
  CommerceHarness(this.tester, {FakeAuthGateway? gateway, FakeBackend? backend, List<Override> overrides = const []})
      : gateway = gateway ?? fixtureGateway(),
        backend = backend ?? fixtureBackend() {
    container = ProviderContainer(
      overrides: [...testOverrides(gateway: this.gateway, backend: this.backend), ...overrides],
      retry: (_, _) => null,
    );
  }

  final WidgetTester tester;
  final FakeAuthGateway gateway;
  final FakeBackend backend;
  late final ProviderContainer container;

  Future<void> start({Size size = const Size(1000, 2400), double textScale = 1.0}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    tester.platformDispatcher.textScaleFactorTestValue = textScale;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearAllTestValues);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const HelmApp()));
    await pump();
  }

  /// Unmounts the app and disposes providers (cancels timers and polling).
  Future<void> stop() async {
    await tester.pumpWidget(const SizedBox());
    container.dispose();
  }

  void go(String location) => container.read(routerProvider).go(location);

  String get location => container.read(routerProvider).routerDelegate.currentConfiguration.uri.toString();

  /// Lets fake HTTP round-trips complete and frames render.
  Future<void> pump([int rounds = 20]) async {
    for (var i = 0; i < rounds; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
      await tester.pump(const Duration(milliseconds: 50));
    }
  }

  Future<void> tap(Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.pump();
    await tester.tap(finder);
    await pump();
  }

  Future<void> enter(String label, String text) async {
    final f = find.widgetWithText(TextField, label);
    await tester.ensureVisible(f);
    await tester.enterText(f, text);
    await tester.pump();
  }
}
