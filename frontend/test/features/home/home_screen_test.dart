// Home in the real app shell, fed with captured server payloads.
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/fakes.dart';
import '../content/engagement_test_helpers.dart';

void main() {
  testWidgets('primary vessel, quick links and synthetic-marked articles from the server', (tester) async {
    final backend = engagementBackend();
    final article = (engMap('content_articles')['items'] as List).first as Map;
    final app = await engagementApp(tester, backend: backend);

    final vessels = (fixture('vessels_list') as List).cast<Map>();
    final primary = vessels.firstWhere((v) => v['is_primary'] == true);
    expect(find.text(primary['nickname'] as String), findsOneWidget);
    expect(find.text('Primary'), findsOneWidget);
    for (final link in ['Garage', 'Parts that fit', 'First Mate', 'Checklists', 'Orders', 'Crew Rewards']) {
      expect(find.text(link), findsWidgets, reason: link);
    }
    expect(find.text('Admin console'), findsNothing, reason: 'customer role');
    expect(find.text('From The Boat Ramp'), findsOneWidget);
    expect(find.text(article['title'] as String), findsOneWidget);
    expect(find.text('Synthetic sample'), findsWidgets);
    expect(find.textContaining('Helm Dash delivery'), findsNothing, reason: 'no active delivery');

    await app.tap(find.text('Checklists').last);
    expect(app.location, '/vessels/${primary['id']}/checklists');
  });

  testWidgets('articles are hidden when the CMS is unavailable or fails', (tester) async {
    final backend = engagementBackend();
    backend.json('GET /content/articles', 503, eng('error_rate_limited'));
    await engagementApp(tester, backend: backend);
    expect(find.text('From The Boat Ramp'), findsNothing);
    expect(find.text('Garage'), findsOneWidget);
  });

  testWidgets('no vessel: prompt to add one; First Mate quick link opens the chat', (tester) async {
    final backend = engagementBackend();
    backend.json('GET /vessels/', 200, fixture('vessels_empty'));
    final app = await engagementApp(tester, backend: backend);
    expect(find.text('Add your boat to see parts that fit it.'), findsOneWidget);
    await app.tap(find.text('First Mate'));
    expect(app.location, '/chat');
  });

  testWidgets('admins see the admin console link', (tester) async {
    final (backend, gateway) = adminSession();
    final app = await engagementApp(tester, backend: backend, gateway: gateway);
    expect(find.text('Admin console'), findsOneWidget);
    backend.json('GET /products/fitment-rules', 200, eng('admin_fitment_rules_unverified'));
    await app.tap(find.text('Admin console'));
    expect(app.location, '/admin');
  });

  testWidgets('article detail renders the server body; a missing article shows the error', (tester) async {
    final backend = engagementBackend();
    final detail = engMap('content_article_detail');
    backend.json('GET /content/articles/${detail['slug']}', 200, detail);
    final app = await engagementApp(tester, backend: backend);
    await app.tap(find.text(detail['title'] as String));
    expect(find.text(detail['body'] as String), findsOneWidget);
    expect(find.text('Synthetic sample — not real advice'), findsOneWidget);

    backend.json('GET /content/articles/no-such-article', 404, eng('error_article_not_found'));
    app.go('/articles/no-such-article');
    await app.settle();
    expect(find.text('Could not load the article'), findsOneWidget);
    expect(find.text(engMap('error_article_not_found')['detail'] as String), findsOneWidget);
  });
}
