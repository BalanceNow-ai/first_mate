import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/features/auth/widgets/auth_scaffold.dart';

/// Shown while the local profile is created/loaded after sign-in, and when
/// that fails (with the server's message, a retry and a way out).
class ProvisioningScreen extends ConsumerWidget {
  const ProvisioningScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final controller = ref.read(authControllerProvider.notifier);

    if (auth.phase != AuthPhase.provisioningFailed) {
      return AuthScaffold(
        title: 'Setting up your account',
        child: Semantics(
          liveRegion: true,
          label: 'Loading your profile',
          child: const Center(child: CircularProgressIndicator()),
        ),
      );
    }

    final error = auth.error;
    return AuthScaffold(
      title: 'We couldn\'t load your account',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InlineError(error?.detail ?? 'Something went wrong.'),
          if (error != null) ...[
            const SizedBox(height: 8),
            Text('Code: ${error.code}', textAlign: TextAlign.center),
          ],
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: controller.retryProvisioning,
            icon: const Icon(Icons.refresh),
            label: const Text('Try again'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: controller.signOut, child: const Text('Sign out')),
        ],
      ),
    );
  }
}
