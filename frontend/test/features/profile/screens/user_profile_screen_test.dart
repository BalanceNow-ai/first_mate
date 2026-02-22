import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/auth/auth_provider.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/features/profile/providers/profile_provider.dart';
import 'package:helm_marine/features/profile/screens/user_profile_screen.dart';

void main() {
  group('UserProfileScreen', () {
    Widget buildTestWidget({
      AsyncValue<User?>? authState,
      AsyncValue<List<Map<String, dynamic>>>? ordersState,
    }) {
      return ProviderScope(
        overrides: [
          if (authState != null)
            authStateProvider.overrideWith(() => _FakeAuthNotifier(authState)),
          if (ordersState != null)
            orderHistoryProvider.overrideWith((ref) async {
              if (ordersState is AsyncError) throw ordersState.error!;
              return ordersState.value!;
            }),
        ],
        child: const MaterialApp(
          home: UserProfileScreen(),
        ),
      );
    }

    testWidgets('shows Profile title in app bar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Profile'), findsOneWidget);
    });

    testWidgets('shows user name and email', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'skipper@helm.co.nz',
          fullName: 'Captain Hook',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Captain Hook'), findsOneWidget);
      expect(find.text('skipper@helm.co.nz'), findsOneWidget);
    });

    testWidgets('shows Edit Profile button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Edit Profile'), findsOneWidget);
    });

    testWidgets('shows Log Out button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Log Out'), findsOneWidget);
    });

    testWidgets('shows empty orders message', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('No orders yet'), findsOneWidget);
    });

    testWidgets('shows order history', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test User',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([
          {
            'id': 'abc12345-6789-0000-0000-000000000000',
            'status': 'paid',
            'total': 125.80,
            'created_at': '2026-02-10T12:00:00Z',
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Order History'), findsOneWidget);
      expect(find.text('Order #ABC12345'), findsOneWidget);
      expect(find.text('\$125.80'), findsOneWidget);
    });

    testWidgets('shows push notifications switch', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Test',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Settings'), findsOneWidget);
      expect(find.text('Push Notifications'), findsOneWidget);
    });

    testWidgets('shows user initials in avatar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        authState: AsyncData(User(
          id: 'u-1',
          email: 'test@helm.co.nz',
          fullName: 'Captain Hook',
          createdAt: DateTime(2026, 1, 1),
        )),
        ordersState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('C'), findsOneWidget); // First letter of Captain
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
