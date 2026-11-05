import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/router.dart';

import '../helpers/fakes.dart';

void main() {
  String? go(AuthState s, String location) => authRedirect(s, Uri.parse(location));
  final user = User.fromJson(fixtureMap('auth_me'));

  test('signed out → /login, remembering the requested page', () {
    const s = AuthState.signedOut();
    expect(go(s, '/'), '/login');
    expect(go(s, '/login'), isNull);
    expect(go(s, '/signup'), isNull);
    expect(go(s, '/check-email'), '/login');
    expect(go(s, '/cart'), '/login?from=%2Fcart');
  });

  test('awaiting confirmation → /check-email', () {
    const s = AuthState.awaitingConfirmation('a@example.test');
    expect(go(s, '/login'), '/check-email');
    expect(go(s, '/check-email'), isNull);
  });

  test('session without a profile → provisioning flow', () {
    const s = AuthState.provisioning('u1');
    expect(go(s, '/'), '/provisioning');
    expect(go(s, '/login?from=%2Fcart'), '/provisioning?from=%2Fcart');
    expect(go(s, '/provisioning'), isNull);
    const failed = AuthState.provisioningFailed(
      'u1',
      ApiError(statusCode: 403, code: 'profile_not_provisioned', detail: 'x'),
    );
    expect(go(failed, '/vessels'), '/provisioning');
  });

  test('signed in leaves auth pages for home or the remembered page', () {
    final s = AuthState.signedIn(user);
    expect(go(s, '/login'), '/');
    expect(go(s, '/provisioning?from=%2Fcart'), '/cart');
    expect(go(s, '/provisioning?from=https%3A%2F%2Fevil.example'), '/');
    expect(go(s, '/vessels'), isNull);
  });
}
