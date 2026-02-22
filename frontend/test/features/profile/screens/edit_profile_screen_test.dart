import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/auth/auth_provider.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/features/profile/screens/edit_profile_screen.dart';

void main() {
  group('EditProfileScreen', () {
    Widget buildTestWidget({AsyncValue<User?>? authState}) {
      return ProviderScope(
        overrides: [
          if (authState != null)
            authStateProvider.overrideWith(() => _FakeAuthNotifier(authState)),
        ],
        child: const MaterialApp(
          home: EditProfileScreen(),
        ),
      );
    }

    testWidgets('shows Edit Profile title in app bar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          phone: '+64211234567',
          createdAt: DateTime(2026, 1, 1),
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Edit Profile'), findsOneWidget);
    });

    testWidgets('shows Full Name and Phone Number fields', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Full Name'), findsOneWidget);
      expect(find.text('Phone Number'), findsOneWidget);
    });

    testWidgets('pre-populates full name from auth state', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Captain Hook',
          createdAt: DateTime(2026, 1, 1),
        )),
      ));
      await tester.pumpAndSettle();

      final nameField = find.widgetWithText(TextFormField, 'Full Name');
      expect(nameField, findsOneWidget);

      // Check the text controller value
      final widget = tester.widget<TextFormField>(nameField);
      expect(widget.controller?.text, 'Captain Hook');
    });

    testWidgets('shows Save Changes button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Save Changes'), findsOneWidget);
    });

    testWidgets('validates name is required', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: '',
          createdAt: DateTime(2026, 1, 1),
        )),
      ));
      await tester.pumpAndSettle();

      // Clear name field and submit
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Full Name'), '');
      await tester.tap(find.text('Save Changes'));
      await tester.pumpAndSettle();

      expect(find.text('Name is required'), findsOneWidget);
    });
  });
}

class _FakeAuthNotifier extends AsyncNotifier<User?> {
  final AsyncValue<User?> _initial;

  _FakeAuthNotifier(this._initial);

  @override
  Future<User?> build() async {
    if (_initial is AsyncError) throw _initial.error!;
    return _initial.value;
  }
}
