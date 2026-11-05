import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// Shown instead of the app when it must not start (missing or unsafe
/// configuration, or Supabase failed to initialise).
class StartupErrorApp extends StatelessWidget {
  const StartupErrorApp({super.key, required this.title, required this.problems, this.hint});

  final String title;
  final List<String> problems;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Helm Marine',
      debugShowCheckedModeBanner: false,
      theme: HelmTheme.light,
      home: Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 560),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.report_gmailerrorred, size: 56, color: HelmTheme.error),
                    const SizedBox(height: 16),
                    Semantics(
                      header: true,
                      child: Text(title, style: Theme.of(context).textTheme.headlineSmall),
                    ),
                    const SizedBox(height: 12),
                    for (final p in problems)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('•  '),
                            Expanded(child: SelectableText(p)),
                          ],
                        ),
                      ),
                    if (hint != null) ...[
                      const SizedBox(height: 12),
                      Text(hint!, style: const TextStyle(color: HelmTheme.mutedText)),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
