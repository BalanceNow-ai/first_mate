import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/app.dart';
import 'package:helm_marine/core/router.dart';

import 'fakes.dart';

/// The real app (router, auth redirects, shell) wired to fakes.
class AppHarness {
  AppHarness(this.tester, {required this.gateway, required this.backend})
      : container = makeContainer(gateway: gateway, backend: backend);

  final WidgetTester tester;
  final FakeAuthGateway gateway;
  final FakeBackend backend;
  final ProviderContainer container;

  Future<void> start({Size size = const Size(420, 900), double textScale = 1.0}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    tester.platformDispatcher.textScaleFactorTestValue = textScale;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearAllTestValues);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const HelmApp()));
    await settle();
  }

  void go(String location) => container.read(routerProvider).go(location);

  String get location =>
      container.read(routerProvider).routerDelegate.currentConfiguration.uri.toString();

  /// Lets fake HTTP round-trips and animations finish.
  Future<void> settle() async {
    for (var i = 0; i < 20; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
      await tester.pump(const Duration(milliseconds: 50));
    }
    await tester.pumpAndSettle();
  }

  Future<void> enter(String label, String text) async {
    await tester.enterText(find.widgetWithText(TextFormField, label), text);
  }

  Future<void> tap(Finder finder) async {
    await tester.ensureVisible(finder);
    await tester.tap(finder);
    await settle();
  }
}
