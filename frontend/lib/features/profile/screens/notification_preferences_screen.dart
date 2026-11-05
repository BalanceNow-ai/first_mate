import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/notification_preferences.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/profile/data/notification_preferences_api.dart';

const _channels = [
  ('email_enabled', 'Email', 'Send notifications by email', Icons.email_outlined),
  ('push_enabled', 'Push notifications', 'Send notifications to your devices', Icons.notifications_outlined),
];

const _topics = [
  ('order_updates', 'Order updates', 'Dispatch and shipping progress', Icons.receipt_long_outlined),
  ('delivery_updates', 'Delivery updates', 'Helm Dash and courier delivery status', Icons.local_shipping_outlined),
  ('service_reminders', 'Service reminders', 'When a vessel service is due', Icons.build_outlined),
  ('rewards_updates', 'Crew rewards', 'Points and rewards activity', Icons.card_giftcard_outlined),
  ('marketing', 'News and offers', 'Promotions and product news', Icons.campaign_outlined),
];

/// Notification preferences (`GET/PUT /notifications/preferences`).
class NotificationPreferencesScreen extends ConsumerWidget {
  const NotificationPreferencesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final prefs = ref.watch(notificationPreferencesProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Notification preferences')),
      body: prefs.when(
        loading: () => const LoadingView(message: 'Loading preferences'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load your preferences',
          onRetry: () => ref.invalidate(notificationPreferencesProvider),
        ),
        data: (p) => _PreferencesList(prefs: p),
      ),
    );
  }
}

class _PreferencesList extends ConsumerWidget {
  const _PreferencesList({required this.prefs});

  final NotificationPreferences prefs;

  Future<void> _set(BuildContext context, WidgetRef ref, String field, bool value) async {
    try {
      await ref.read(notificationPreferencesProvider.notifier).set(field, value);
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Not saved');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final heading = theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold);
    Widget tile((String, String, String, IconData) spec) {
      final (field, title, subtitle, icon) = spec;
      return SwitchListTile(
        secondary: Icon(icon),
        title: Text(title),
        subtitle: Text(subtitle),
        value: prefs.value(field),
        activeThumbColor: HelmTheme.primary,
        onChanged: (v) => _set(context, ref, field, v),
      );
    }

    return ContentWidth(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: HelmTheme.primary.withValues(alpha: 0.08),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, color: HelmTheme.primary),
                  const SizedBox(width: 12),
                  Expanded(child: Text(prefs.transactionalNote)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Semantics(header: true, child: Text('How we contact you', style: heading)),
          Card(child: Column(children: [for (final c in _channels) tile(c)])),
          const SizedBox(height: 16),
          Semantics(header: true, child: Text('What we tell you about', style: heading)),
          Card(child: Column(children: [for (final t in _topics) tile(t)])),
        ],
      ),
    );
  }
}
