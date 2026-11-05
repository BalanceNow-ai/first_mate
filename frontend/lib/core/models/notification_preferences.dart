import 'package:helm_marine/core/models/json.dart';

/// `PreferencesOut` for `GET/PUT /notifications/preferences`.
class NotificationPreferences {
  const NotificationPreferences({
    required this.emailEnabled,
    required this.pushEnabled,
    required this.orderUpdates,
    required this.deliveryUpdates,
    required this.serviceReminders,
    required this.rewardsUpdates,
    required this.marketing,
    required this.transactionalNote,
  });

  /// Wire names of the boolean preferences (the `PreferencesUpdate` fields).
  static const fields = [
    'email_enabled',
    'push_enabled',
    'order_updates',
    'delivery_updates',
    'service_reminders',
    'rewards_updates',
    'marketing',
  ];

  final bool emailEnabled;
  final bool pushEnabled;
  final bool orderUpdates;
  final bool deliveryUpdates;
  final bool serviceReminders;
  final bool rewardsUpdates;
  final bool marketing;

  /// Server text explaining which emails are always sent.
  final String transactionalNote;

  bool value(String field) => switch (field) {
        'email_enabled' => emailEnabled,
        'push_enabled' => pushEnabled,
        'order_updates' => orderUpdates,
        'delivery_updates' => deliveryUpdates,
        'service_reminders' => serviceReminders,
        'rewards_updates' => rewardsUpdates,
        'marketing' => marketing,
        _ => throw ArgumentError.value(field, 'field'),
      };

  NotificationPreferences withValue(String field, bool v) => NotificationPreferences(
        emailEnabled: field == 'email_enabled' ? v : emailEnabled,
        pushEnabled: field == 'push_enabled' ? v : pushEnabled,
        orderUpdates: field == 'order_updates' ? v : orderUpdates,
        deliveryUpdates: field == 'delivery_updates' ? v : deliveryUpdates,
        serviceReminders: field == 'service_reminders' ? v : serviceReminders,
        rewardsUpdates: field == 'rewards_updates' ? v : rewardsUpdates,
        marketing: field == 'marketing' ? v : marketing,
        transactionalNote: transactionalNote,
      );

  factory NotificationPreferences.fromJson(Map<String, dynamic> json) => NotificationPreferences(
        emailEnabled: req<bool>(json, 'email_enabled'),
        pushEnabled: req<bool>(json, 'push_enabled'),
        orderUpdates: req<bool>(json, 'order_updates'),
        deliveryUpdates: req<bool>(json, 'delivery_updates'),
        serviceReminders: req<bool>(json, 'service_reminders'),
        rewardsUpdates: req<bool>(json, 'rewards_updates'),
        marketing: req<bool>(json, 'marketing'),
        transactionalNote: req<String>(json, 'transactional_note'),
      );
}
