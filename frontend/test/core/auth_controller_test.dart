import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/auth/auth_gateway.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

import '../helpers/fakes.dart';

const userA = '11111111-1111-4111-8111-111111111111';
const userB = '22222222-2222-4222-8222-222222222222';

Map<String, dynamic> profile(String id, String email, {String? name}) => {
      ...fixtureMap('auth_me'),
      'id': id,
      'email': email,
      'full_name': name,
    };

Map<String, dynamic> vesselFor(String owner, String nickname) => {
      ...fixtureMap('vessel_create'),
      'id': '$owner-v',
      'user_id': owner,
      'nickname': nickname,
    };

/// A backend that answers per token, like the real API (identity = token subject).
FakeBackend multiUserBackend() {
  final backend = FakeBackend();
  final users = {
    'Bearer token-a': (userA, 'a@example.test', 'Alice', 'Alice Boat'),
    'Bearer token-b': (userB, 'b@example.test', 'Bob', 'Bob Boat'),
  };
  backend.on('POST /auth/provision', (r) {
    final u = users[r.authorization];
    if (u == null) return const FakeResponse(401, {'detail': 'Authentication required', 'code': 'invalid_token'});
    return FakeResponse(200, {...profile(u.$1, u.$2, name: u.$3), 'created': false});
  });
  backend.on('GET /auth/me', (r) {
    final u = users[r.authorization];
    if (u == null) return const FakeResponse(401, {'detail': 'Authentication required', 'code': 'invalid_token'});
    return FakeResponse(200, profile(u.$1, u.$2, name: u.$3));
  });
  backend.on('GET /vessels/', (r) {
    final u = users[r.authorization];
    if (u == null) return const FakeResponse(401, {'detail': 'Authentication required', 'code': 'invalid_token'});
    return FakeResponse(200, [vesselFor(u.$1, u.$4)]);
  });
  backend.on('GET /cart/', (r) => FakeResponse(200, fixture('cart_with_item')));
  return backend;
}

FakeAuthGateway multiUserGateway() => FakeAuthGateway()
  ..accounts['a@example.test'] = ('password-a', userA, 'token-a')
  ..accounts['b@example.test'] = ('password-b', userB, 'token-b');

void main() {
  test('a restored session is provisioned then loaded (identity from token only)', () async {
    final backend = fixtureBackend();
    final gateway = fixtureGateway()..fullNameHint = 'Fixture Skipper';
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);

    expect(container.read(authControllerProvider).phase, AuthPhase.provisioning);
    await until(() => container.read(authControllerProvider).isSignedIn);
    final state = container.read(authControllerProvider);
    expect(state.phase, AuthPhase.signedIn);
    expect(state.user!.fullName, 'Fixture Skipper');

    final provision = backend.calls('POST /auth/provision').single;
    expect(provision.body, {'full_name': 'Fixture Skipper'});
    expect(provision.authorization, 'Bearer token-a');
    expect(backend.calls('GET /auth/me'), hasLength(1));
  });

  test('sign up with a session (confirmation disabled) provisions and signs in', () async {
    final backend = multiUserBackend();
    final gateway = multiUserGateway();
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);

    await container
        .read(authControllerProvider.notifier)
        .signUp(email: 'a@example.test', password: 'pw', fullName: 'Alice Example');

    final state = container.read(authControllerProvider);
    expect(state.phase, AuthPhase.signedIn);
    expect(state.userId, userA);
    final bodies = backend.calls('POST /auth/provision').map((r) => r.body).toList();
    expect(bodies, isNotEmpty);
    for (final body in bodies) {
      expect(body, {'full_name': 'Alice Example'}, reason: 'never id / email / role');
    }
  });

  test('sign up without a session (confirmation required) waits for the email', () async {
    final backend = multiUserBackend();
    final gateway = multiUserGateway()..signUpReturnsSession = false;
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);
    final controller = container.read(authControllerProvider.notifier);

    await controller.signUp(email: 'new@example.test', password: 'pw12345678', fullName: 'New');
    expect(container.read(authControllerProvider).phase, AuthPhase.awaitingConfirmation);
    expect(container.read(authControllerProvider).email, 'new@example.test');
    expect(backend.requests, isEmpty, reason: 'nothing is provisioned without a session');

    await controller.resendConfirmation();
    expect(gateway.resent, ['new@example.test']);

    controller.backToSignIn();
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);
  });

  test('sign-in failures surface the provider message', () async {
    final container = makeContainer(gateway: multiUserGateway(), backend: multiUserBackend());
    addTearDown(container.dispose);
    await expectLater(
      container.read(authControllerProvider.notifier).signIn(email: 'a@example.test', password: 'wrong'),
      throwsA(isA<AuthFailure>().having((e) => e.message, 'message', 'Invalid login credentials')),
    );
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);
  });

  test('provisioning failure exposes {detail, code} and can be retried', () async {
    final backend = fixtureBackend();
    var fail = true;
    backend.on('POST /auth/provision', (_) => fail
        ? const FakeResponse(409, {
            'detail': 'This email is already linked to a different account. Contact support.',
            'code': 'email_bound_to_other_account',
          })
        : FakeResponse(200, fixture('provision_existing')));
    final container = makeContainer(gateway: fixtureGateway(), backend: backend);
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await until(() => container.read(authControllerProvider).phase == AuthPhase.provisioningFailed);

    var state = container.read(authControllerProvider);
    expect(state.error!.code, 'email_bound_to_other_account');
    expect(state.error!.detail, contains('different account'));

    fail = false;
    await container.read(authControllerProvider.notifier).retryProvisioning();
    state = container.read(authControllerProvider);
    expect(state.phase, AuthPhase.signedIn);
  });

  test('sign out clears user data; a second account never sees the first account\'s data', () async {
    final backend = multiUserBackend();
    final gateway = multiUserGateway();
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);
    final controller = container.read(authControllerProvider.notifier);
    // Keep the user-scoped providers alive like mounted screens do.
    final vesselsSub = container.listen(vesselListProvider, (_, _) {});
    final cartSub = container.listen(cartProvider, (_, _) {});
    addTearDown(vesselsSub.close);
    addTearDown(cartSub.close);

    await controller.signIn(email: 'a@example.test', password: 'password-a');
    final aVessels = await container.read(vesselListProvider.future);
    expect(aVessels.map((Vessel v) => v.nickname), ['Alice Boat']);
    expect((await container.read(cartProvider.future)).items, isNotEmpty);

    await controller.signOut();
    expect(gateway.signOutCalls, 1);
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);
    expect(container.read(currentUserIdProvider), isNull);
    expect(await container.read(vesselListProvider.future), isEmpty);
    expect((await container.read(cartProvider.future)).items, isEmpty);

    await controller.signIn(email: 'b@example.test', password: 'password-b');
    final bVessels = await container.read(vesselListProvider.future);
    expect(bVessels.map((v) => v.nickname), ['Bob Boat']);
    expect(bVessels.any((v) => v.userId == userA), isFalse);
    // Every vessel request after the switch carried B's token.
    final afterSwitch = backend.calls('GET /vessels/').last;
    expect(afterSwitch.authorization, 'Bearer token-b');
  });

  test('a different user arriving via onAuthStateChange replaces the old user\'s data', () async {
    final backend = multiUserBackend();
    final gateway = multiUserGateway();
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);
    final sub = container.listen(vesselListProvider, (_, _) {});
    addTearDown(sub.close);

    await container.read(authControllerProvider.notifier).signIn(email: 'a@example.test', password: 'password-a');
    expect((await container.read(vesselListProvider.future)).single.nickname, 'Alice Boat');

    // Another tab signs in as B: Supabase reports a session for a different subject.
    gateway.setSession(userId: userB, token: 'token-b', email: 'b@example.test');
    gateway.emit(const AuthEvent(AuthEventType.signedIn, userId: userB, email: 'b@example.test'));
    expect(container.read(currentUserIdProvider), isNull, reason: 'A\'s data is dropped immediately');
    await until(() => container.read(authControllerProvider).isSignedIn);

    expect(container.read(authControllerProvider).userId, userB);
    expect((await container.read(vesselListProvider.future)).single.nickname, 'Bob Boat');
  });

  test('a refresh failure (session expired) signs the user out', () async {
    final backend = fixtureBackend();
    final gateway = fixtureGateway();
    final container = makeContainer(gateway: gateway, backend: backend);
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await until(() => container.read(authControllerProvider).isSignedIn);

    backend.json('GET /vessels/', 401, {'detail': 'Authentication token has expired', 'code': 'invalid_token'});
    gateway.refreshedToken = null;
    await expectLater(container.read(vesselListProvider.future), throwsA(anything));
    await until(() => gateway.signOutCalls == 1);
    expect(gateway.refreshCalls, 1);
    expect(gateway.signOutCalls, 1);
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);
  });

  test('an external sign-out event (e.g. another tab) signs out here too', () async {
    final container = makeContainer(gateway: fixtureGateway(), backend: fixtureBackend());
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await until(() => container.read(authControllerProvider).isSignedIn);
    final gateway = container.read(authGatewayProvider) as FakeAuthGateway;
    gateway.emit(const AuthEvent(AuthEventType.signedOut));
    expect(container.read(authControllerProvider).phase, AuthPhase.signedOut);
  });
}
