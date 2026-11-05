import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// Centred, width-limited card layout shared by the sign-in flow screens.
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({super.key, required this.title, required this.child, this.subtitle});

  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: HelmTheme.surface,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.sailing, size: 64, color: HelmTheme.navy, semanticLabel: 'Helm Marine'),
                  const SizedBox(height: 12),
                  Semantics(
                    header: true,
                    child: Text(
                      title,
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: HelmTheme.navy,
                      ),
                    ),
                  ),
                  if (subtitle != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      subtitle!,
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyLarge?.copyWith(color: HelmTheme.mutedText),
                    ),
                  ],
                  const SizedBox(height: 32),
                  child,
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Inline error text announced to screen readers.
class InlineError extends StatelessWidget {
  const InlineError(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: HelmTheme.error.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: HelmTheme.error.withValues(alpha: 0.4)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline, color: HelmTheme.error, size: 20),
            const SizedBox(width: 8),
            Expanded(child: Text(message, style: const TextStyle(color: HelmTheme.error))),
          ],
        ),
      ),
    );
  }
}

/// Always-present slot for an optional [InlineError], so widgets after it keep
/// their positions (and their state) when the error appears or disappears.
class InlineErrorSlot extends StatelessWidget {
  const InlineErrorSlot(this.message, {super.key});

  final String? message;

  @override
  Widget build(BuildContext context) {
    if (message == null) return const SizedBox.shrink();
    return Padding(padding: const EdgeInsets.only(bottom: 16), child: InlineError(message!));
  }
}

String? validateEmail(String? value) {
  final v = value?.trim() ?? '';
  if (v.isEmpty) return 'Enter your email';
  if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(v)) return 'Enter a valid email address';
  return null;
}
