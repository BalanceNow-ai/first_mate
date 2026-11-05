import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:helm_marine/core/router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

class HelmApp extends ConsumerWidget {
  const HelmApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    // Fetch the server's public configuration as soon as the app starts.
    ref.watch(publicConfigProvider);

    return MaterialApp.router(
      title: 'Helm Marine',
      debugShowCheckedModeBanner: false,
      theme: HelmTheme.light,
      darkTheme: HelmTheme.dark,
      themeMode: ThemeMode.light,
      routerConfig: router,
    );
  }
}
