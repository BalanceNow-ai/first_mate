import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/auth/widgets/auth_scaffold.dart';

/// Shown after sign-up when Supabase requires email confirmation.
class CheckEmailScreen extends ConsumerStatefulWidget {
  const CheckEmailScreen({super.key});

  @override
  ConsumerState<CheckEmailScreen> createState() => _CheckEmailScreenState();
}

class _CheckEmailScreenState extends ConsumerState<CheckEmailScreen> {
  bool _sending = false;
  String? _status;
  bool _statusIsError = false;

  Future<void> _resend() async {
    setState(() {
      _sending = true;
      _status = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).resendConfirmation();
      if (mounted) {
        setState(() {
          _status = 'Confirmation email sent again.';
          _statusIsError = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _status = describeError(e);
          _statusIsError = true;
        });
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final email = ref.watch(authControllerProvider.select((s) => s.email)) ?? 'your inbox';
    return AuthScaffold(
      title: 'Check your email',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.mark_email_unread_outlined, size: 48, color: HelmTheme.ocean),
          const SizedBox(height: 16),
          Text(
            'We sent a confirmation link to $email. Open it to activate your '
            'account, then sign in.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 24),
          if (_status != null) ...[
            _statusIsError
                ? InlineError(_status!)
                : Semantics(
                    liveRegion: true,
                    child: Text(_status!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: HelmTheme.success)),
                  ),
            const SizedBox(height: 16),
          ],
          OutlinedButton.icon(
            onPressed: _sending ? null : _resend,
            icon: const Icon(Icons.refresh),
            label: Text(_sending ? 'Sending…' : 'Resend confirmation email'),
          ),
          const SizedBox(height: 12),
          ElevatedButton(
            onPressed: () => ref.read(authControllerProvider.notifier).backToSignIn(),
            child: const Text('Back to sign in'),
          ),
        ],
      ),
    );
  }
}
