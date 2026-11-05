import 'package:flutter/material.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// Centred progress indicator with an accessible label.
class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.message});

  final String? message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Semantics(
        label: message ?? 'Loading',
        liveRegion: true,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            if (message != null) ...[
              const SizedBox(height: 16),
              Text(message!, textAlign: TextAlign.center),
            ],
          ],
        ),
      ),
    );
  }
}

/// An error with the server's message (`detail`) and an optional retry.
class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.title, this.onRetry});

  final Object error;
  final String? title;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final api = ApiError.from(error);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 48, color: HelmTheme.error),
              const SizedBox(height: 16),
              if (title != null)
                Text(title!,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Text(describeError(error), textAlign: TextAlign.center),
              if (api != null && api.code.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text('Code: ${api.code}',
                    style: Theme.of(context)
                        .textTheme
                        .bodySmall
                        ?.copyWith(color: HelmTheme.mutedText)),
              ],
              if (onRetry != null) ...[
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Try again'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Shows an error message from any thrown object in a SnackBar.
void showErrorSnackBar(BuildContext context, Object error, {String? prefix}) {
  final message = describeError(error);
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(prefix == null ? message : '$prefix: $message'),
    backgroundColor: HelmTheme.error,
  ));
}

/// Constrains content to a readable width on wide (web/desktop) layouts.
class ContentWidth extends StatelessWidget {
  const ContentWidth({super.key, required this.child, this.maxWidth = 720});

  final Widget child;
  final double maxWidth;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: child,
      ),
    );
  }
}
