import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';

/// The signed-in user as `/auth/me` reports it now (roles can change while
/// signed in, e.g. through the audited `grant-role` CLI).
final staffMeProvider = FutureProvider.autoDispose<User>((ref) {
  return ref.watch(userApiProvider).getCurrentUser();
});

/// Whether [role] may use a screen meant for [roles] (admin is implied, as on the server).
bool roleAllows(String role, Set<String> roles) => role == 'admin' || roles.contains(role);

/// Shows [builder] only to users holding one of [roles] (or admin). The server
/// still authorises every call; its 403 responses are shown where they occur.
class RoleGate extends ConsumerWidget {
  const RoleGate({super.key, required this.roles, required this.title, required this.builder});

  final Set<String> roles;
  final String title;
  final Widget Function(BuildContext context, User me) builder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(staffMeProvider);
    return me.when(
      loading: () => Scaffold(appBar: AppBar(title: Text(title)), body: const LoadingView()),
      error: (e, _) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: ErrorView(error: e, onRetry: () => ref.invalidate(staffMeProvider)),
      ),
      data: (user) {
        if (!roleAllows(user.role, roles)) {
          return Scaffold(
            appBar: AppBar(title: Text(title)),
            body: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.lock_outline, size: 48, color: HelmTheme.mutedText),
                  const SizedBox(height: 12),
                  Text('$title is only available to ${roles.join(' / ')} accounts.', textAlign: TextAlign.center),
                  const SizedBox(height: 4),
                  Text('Your role: ${user.role}', style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
            ),
          );
        }
        return builder(context, user);
      },
    );
  }
}

/// Runs a staff action, reporting success or the server's `{detail, code}`.
Future<T?> runStaffAction<T>(
  BuildContext context,
  Future<T> Function() action, {
  String? success,
}) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    final result = await action();
    if (success != null) messenger.showSnackBar(SnackBar(content: Text(success)));
    return result;
  } catch (e) {
    final api = ApiError.from(e);
    messenger.showSnackBar(SnackBar(
      backgroundColor: HelmTheme.error,
      content: Text(api == null ? describeError(e) : '${staffErrorText(api)} (${api.code})'),
    ));
    return null;
  }
}

/// Staff-facing explanations for server codes.
String staffErrorText(ApiError e) => switch (e.code) {
      'forbidden' => 'You do not have permission to do that.',
      'rate_unconfigured' =>
        'No operator share is configured, so this payout has no amount and cannot be approved. Live payouts are disabled.',
      'location_stale' => 'That position reading is too old to share as a live position. Take a new reading.',
      'location_in_future' => 'That reading is time-stamped in the future — check the device clock.',
      'not_trackable' => e.detail,
      'operator_not_active' => e.detail,
      'operator_wrong_area' => 'That operator does not serve this delivery\'s area.',
      _ => e.detail,
    };

/// Asks for an optional reason; returns null when cancelled.
Future<String?> askReason(BuildContext context, {required String title, required String action, bool required = false}) {
  final controller = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: controller,
        maxLength: 500,
        decoration: InputDecoration(labelText: required ? 'Reason *' : 'Reason (optional)'),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Back')),
        FilledButton(
          onPressed: () {
            if (required && controller.text.trim().length < 3) return;
            Navigator.pop(context, controller.text.trim());
          },
          child: Text(action),
        ),
      ],
    ),
  ).whenComplete(controller.dispose);
}

/// A simple yes/no confirmation.
Future<bool> confirmAction(BuildContext context, {required String title, required String message, required String action}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Back')),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(action)),
      ],
    ),
  );
  return ok == true;
}

/// A titled card section.
class StaffSection extends StatelessWidget {
  const StaffSection({super.key, required this.title, required this.child, this.trailing});

  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(children: [
              Expanded(
                child: Semantics(header: true, child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
              ),
              ?trailing,
            ]),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}
