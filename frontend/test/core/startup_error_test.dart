import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/config/app_config.dart';
import 'package:helm_marine/core/startup/startup_error_app.dart';

void main() {
  testWidgets('an unconfigured release build shows a clear error screen', (tester) async {
    final problems = AppConfig.resolve(isRelease: true).problems();
    await tester.pumpWidget(StartupErrorApp(title: 'Helm is not configured', problems: problems));
    expect(find.text('Helm is not configured'), findsOneWidget);
    expect(find.textContaining('API_BASE_URL is not set'), findsOneWidget);
    expect(find.textContaining('SUPABASE_URL is not set'), findsOneWidget);
    expect(find.byType(SelectableText), findsNWidgets(problems.length));
  });
}
