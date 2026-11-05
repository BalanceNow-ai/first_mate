// Journey J1 at widget level: the real app (router, redirects, shell, screens)
// against a fake Supabase gateway and a fake API that answers per token.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../core/auth_controller_test.dart' show multiUserBackend, multiUserGateway;
import '../helpers/app_harness.dart';
import '../helpers/fakes.dart';

void main() {
  testWidgets('signed out users land on sign-in; bad credentials show the provider message',
      (tester) async {
    final app = AppHarness(tester, gateway: multiUserGateway(), backend: multiUserBackend());
    await app.start();
    expect(app.location, '/login');
    expect(find.text('Sign in to your account'), findsOneWidget);

    await app.enter('Email', 'a@example.test');
    await app.enter('Password', 'wrong-password');
    await app.tap(find.widgetWithText(ElevatedButton, 'Sign In'));
    expect(find.text('Invalid login credentials'), findsOneWidget);
    expect(app.location, '/login');
  });

  testWidgets('sign up with email confirmation → check your email → resend → back', (tester) async {
    final gateway = multiUserGateway()..signUpReturnsSession = false;
    final app = AppHarness(tester, gateway: gateway, backend: multiUserBackend());
    await app.start();
    await app.tap(find.text("Don't have an account? Sign up"));
    expect(app.location, '/signup');

    await app.enter('Full name', 'New Skipper');
    await app.enter('Email', 'new@example.test');
    await app.enter('Password', 'longenough1');
    await app.enter('Confirm password', 'longenough1');
    await app.tap(find.widgetWithText(ElevatedButton, 'Create Account'));

    expect(app.location, '/check-email');
    expect(find.text('Check your email'), findsOneWidget);
    expect(find.textContaining('new@example.test'), findsOneWidget);
    expect(app.backend.calls('POST /auth/provision'), isEmpty,
        reason: 'no provisioning without a session');

    await app.tap(find.text('Resend confirmation email'));
    expect(gateway.resent, ['new@example.test']);
    expect(find.text('Confirmation email sent again.'), findsOneWidget);

    await app.tap(find.text('Back to sign in'));
    expect(app.location, '/login');
  });

  testWidgets('sign up without confirmation provisions and opens home', (tester) async {
    final app = AppHarness(tester, gateway: multiUserGateway(), backend: multiUserBackend());
    await app.start();
    app.go('/signup');
    await app.settle();
    await app.enter('Full name', 'Alice');
    await app.enter('Email', 'a@example.test');
    await app.enter('Password', 'password-a');
    await app.enter('Confirm password', 'password-a');
    await app.tap(find.widgetWithText(ElevatedButton, 'Create Account'));

    expect(app.location, '/');
    expect(find.text('Kia ora, Alice'), findsOneWidget);
    expect(find.text('Alice Boat'), findsOneWidget);
    expect(app.backend.calls('POST /auth/provision').first.body, {'full_name': 'Alice'});
  });

  testWidgets('sign out clears the first account; the second account sees only its data',
      (tester) async {
    final app = AppHarness(tester, gateway: multiUserGateway(), backend: multiUserBackend());
    await app.start();
    await app.enter('Email', 'a@example.test');
    await app.enter('Password', 'password-a');
    await app.tap(find.widgetWithText(ElevatedButton, 'Sign In'));
    expect(find.text('Alice Boat'), findsOneWidget);

    await app.tap(find.byTooltip('Sign out'));
    expect(app.location, '/login');
    expect(app.gateway.signOutCalls, 1);

    await app.enter('Email', 'b@example.test');
    await app.enter('Password', 'password-b');
    await app.tap(find.widgetWithText(ElevatedButton, 'Sign In'));
    expect(find.text('Kia ora, Bob'), findsOneWidget);
    expect(find.text('Bob Boat'), findsOneWidget);
    expect(find.text('Alice Boat'), findsNothing);

    app.go('/vessels');
    await app.settle();
    expect(find.text('Bob Boat'), findsOneWidget);
    expect(find.text('Alice Boat'), findsNothing);
  });

  testWidgets('a persisted session is restored on reload without signing in', (tester) async {
    final app = AppHarness(tester, gateway: fixtureGateway(), backend: fixtureBackend());
    await app.start();
    expect(app.location, '/');
    expect(find.text('Kia ora, Fixture Skipper'), findsOneWidget);
    expect(find.text('Sea Biscuit'), findsOneWidget);
  });

  testWidgets('a provisioning error shows {detail, code} with retry and sign out', (tester) async {
    final backend = fixtureBackend();
    var fail = true;
    backend.on('POST /auth/provision', (_) => fail
        ? const FakeResponse(409, {
            'detail': 'This email is already linked to a different account. Contact support.',
            'code': 'email_bound_to_other_account',
          })
        : FakeResponse(200, fixture('provision_existing')));
    final app = AppHarness(tester, gateway: fixtureGateway(), backend: backend);
    await app.start();
    expect(app.location, '/provisioning');
    expect(find.textContaining('already linked to a different account'), findsOneWidget);
    expect(find.text('Code: email_bound_to_other_account'), findsOneWidget);

    fail = false;
    await app.tap(find.text('Try again'));
    expect(app.location, '/');
  });

  testWidgets('deep links survive sign-in', (tester) async {
    final app = AppHarness(tester, gateway: multiUserGateway(), backend: multiUserBackend());
    await app.start();
    app.go('/vessels');
    await app.settle();
    expect(app.location, '/login?from=%2Fvessels');
    await app.enter('Email', 'a@example.test');
    await app.enter('Password', 'password-a');
    await app.tap(find.widgetWithText(ElevatedButton, 'Sign In'));
    expect(app.location, '/vessels');
  });
}
