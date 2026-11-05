import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../products/catalogue_backend.dart';

SwitchListTile tile(WidgetTester tester, String title) =>
    tester.widget<SwitchListTile>(find.widgetWithText(SwitchListTile, title));

void main() {
  testWidgets('shows preferences with the transactional note; toggles save one field', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET /orders/', 200, []);
    backend.json('GET /notifications/preferences', 200, cat('notification_preferences'));
    backend.json('PUT /notifications/preferences', 200, {
      ...cat('notification_preferences'),
      'marketing': true,
    });
    final app = await startApp(tester, backend, size: const Size(600, 1400));
    app.go('/profile');
    await app.settle();
    await app.tap(find.text('Notification preferences'));
    expect(app.location, '/profile/notifications');

    expect(find.text('Order confirmations and refund receipts are always sent by email.'), findsOneWidget);
    expect(tile(tester, 'News and offers').value, isFalse);
    expect(tile(tester, 'Email').value, isTrue);

    await app.tap(find.text('News and offers'));
    expect(backend.calls('PUT /notifications/preferences').single.body, {'marketing': true});
    expect(tile(tester, 'News and offers').value, isTrue);
  });

  testWidgets('a refused change is rolled back with the server detail', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET /notifications/preferences', 200, cat('notification_preferences'));
    backend.json('PUT /notifications/preferences', 422, cat('error_preferences_unknown_field'));
    final app = await startApp(tester, backend, size: const Size(600, 1400));
    app.go('/profile/notifications');
    await app.settle();

    await app.tap(find.text('Push notifications'));
    expect(tile(tester, 'Push notifications').value, isTrue, reason: 'rolled back');
    expect(find.textContaining('Not saved: Request validation failed'), findsOneWidget);
  });

  testWidgets('load errors offer a retry', (tester) async {
    final backend = catalogueBackend();
    backend.json('GET /notifications/preferences', 503, {'detail': 'Service unavailable', 'code': 'unavailable'});
    final app = await startApp(tester, backend, size: const Size(600, 1400));
    app.go('/profile/notifications');
    await app.settle();
    expect(find.text('Could not load your preferences'), findsOneWidget);
    backend.json('GET /notifications/preferences', 200, cat('notification_preferences'));
    await app.tap(find.text('Try again'));
    expect(find.text('News and offers'), findsOneWidget);
  });
}
