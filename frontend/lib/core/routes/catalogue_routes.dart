import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/profile/screens/notification_preferences_screen.dart';

/// Additional in-shell routes owned by the catalogue client workstream.
final List<RouteBase> catalogueRoutes = <RouteBase>[
  GoRoute(
    path: '/profile/notifications',
    builder: (context, state) => const NotificationPreferencesScreen(),
  ),
];
