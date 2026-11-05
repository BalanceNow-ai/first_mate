import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/admin/screens/admin_console_screen.dart';
import 'package:helm_marine/features/content/screens/article_screen.dart';

/// Additional in-shell routes owned by the engagement client workstream
/// (First Mate, Crew Rewards, content and admin curation). `/`, `/chat` and
/// `/crew` stay in `router.dart`.
final List<RouteBase> engagementRoutes = <RouteBase>[
  GoRoute(path: '/admin', builder: (context, state) => const AdminConsoleScreen()),
  GoRoute(
    path: '/articles/:slug',
    builder: (context, state) => ArticleScreen(slug: state.pathParameters['slug']!),
  ),
];
