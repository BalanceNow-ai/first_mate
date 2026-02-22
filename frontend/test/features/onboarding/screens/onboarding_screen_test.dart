import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/onboarding/screens/onboarding_screen.dart';

void main() {
  group('OnboardingScreen', () {
    Widget buildTestWidget() {
      return const MaterialApp(
        home: OnboardingScreen(),
      );
    }

    testWidgets('shows Welcome to Helm! heading', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.text('Welcome to Helm!'), findsOneWidget);
    });

    testWidgets('shows boat explanation text', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(
        find.textContaining('Add your boat to get personalised'),
        findsOneWidget,
      );
    });

    testWidgets('shows Add My First Boat button', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.text('Add My First Boat'), findsOneWidget);
      expect(find.byIcon(Icons.directions_boat), findsOneWidget);
    });

    testWidgets('shows Skip for now button', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.text('Skip for now'), findsOneWidget);
    });

    testWidgets('shows sailing icon', (tester) async {
      await tester.pumpWidget(buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.sailing), findsOneWidget);
    });
  });
}
