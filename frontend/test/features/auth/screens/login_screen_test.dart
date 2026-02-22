import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/auth/auth_provider.dart';
import 'package:helm_marine/features/auth/screens/login_screen.dart';

void main() {
  group('LoginScreen', () {
    Widget buildTestWidget({AsyncValue<User?>? authState}) {
      return ProviderScope(
        overrides: [
          if (authState != null)
            authStateProvider.overrideWith(() => _FakeAuthNotifier(authState)),
        ],
        child: const MaterialApp(
          home: LoginScreen(),
        ),
      );
    }

    testWidgets('renders email and password fields', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(authState: const AsyncData(null)),
      );

      expect(find.text('Helm Marine'), findsOneWidget);
      expect(find.text('Sign in to your account'), findsOneWidget);
      expect(find.widgetWithText(TextFormField, 'Email'), findsOneWidget);
      expect(find.widgetWithText(TextFormField, 'Password'), findsOneWidget);
      expect(find.text('Sign In'), findsOneWidget);
    });

    testWidgets('shows validation errors on empty submit', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(authState: const AsyncData(null)),
      );

      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Please enter your email'), findsOneWidget);
      expect(find.text('Please enter your password'), findsOneWidget);
    });

    testWidgets('shows validation for invalid email', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(authState: const AsyncData(null)),
      );

      await tester.enterText(
          find.widgetWithText(TextFormField, 'Email'), 'notanemail');
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Password'), '123456');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Please enter a valid email'), findsOneWidget);
    });

    testWidgets('shows validation for short password', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(authState: const AsyncData(null)),
      );

      await tester.enterText(
          find.widgetWithText(TextFormField, 'Email'), 'test@test.com');
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Password'), '123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(
          find.text('Password must be at least 6 characters'), findsOneWidget);
    });

    testWidgets('has link to signup screen', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(authState: const AsyncData(null)),
      );

      expect(find.text("Don't have an account? Sign up"), findsOneWidget);
    });
  });
}

class _FakeAuthNotifier extends AuthNotifier {
  final AsyncValue<User?> _initial;
  _FakeAuthNotifier(this._initial);

  @override
  Future<User?> build() async {
    state = _initial;
    return _initial.valueOrNull;
  }
}
