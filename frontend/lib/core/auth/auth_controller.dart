import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/auth/auth_gateway.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';

/// Where the user is in the identity flow.
enum AuthPhase {
  /// No Supabase session.
  signedOut,

  /// Signed up with email confirmation required; no session yet.
  awaitingConfirmation,

  /// Session present; creating/loading the local profile.
  provisioning,

  /// Session present but the profile could not be provisioned or loaded.
  provisioningFailed,

  /// Session present and the profile is loaded.
  signedIn,
}

class AuthState {
  const AuthState._(this.phase, {this.userId, this.email, this.user, this.error});

  const AuthState.signedOut() : this._(AuthPhase.signedOut);

  const AuthState.awaitingConfirmation(String email)
      : this._(AuthPhase.awaitingConfirmation, email: email);

  const AuthState.provisioning(String userId, {String? email})
      : this._(AuthPhase.provisioning, userId: userId, email: email);

  const AuthState.provisioningFailed(String userId, ApiError error, {String? email})
      : this._(AuthPhase.provisioningFailed, userId: userId, email: email, error: error);

  AuthState.signedIn(User user)
      : this._(AuthPhase.signedIn, userId: user.id, email: user.email, user: user);

  final AuthPhase phase;

  /// Supabase subject of the current session (null when signed out).
  final String? userId;
  final String? email;

  /// The provisioned profile (only when [phase] is [AuthPhase.signedIn]).
  final User? user;

  /// Why provisioning failed (`{detail, code}` from the server).
  final ApiError? error;

  bool get isSignedIn => phase == AuthPhase.signedIn;
}

/// Owns the identity flow: Supabase session → `POST /auth/provision` →
/// `GET /auth/me`. Listens to Supabase auth events so a restored session, a
/// sign-in from elsewhere or a different user's session is picked up, and a
/// sign-out (explicit or after a failed refresh) returns to the signed-out state.
///
/// All user-scoped data hangs off [AuthState.userId] (see `session.dart`), so
/// any change of user discards the previous user's cached providers.
class AuthController extends Notifier<AuthState> {
  late AuthGateway _gateway;
  Future<void>? _inflight;
  String? _inflightFor;

  @override
  AuthState build() {
    _gateway = ref.watch(authGatewayProvider);
    final subscription = _gateway.events.listen(_onEvent);
    ref.onDispose(subscription.cancel);
    final userId = _gateway.currentUserId;
    if (userId == null) return const AuthState.signedOut();
    // A persisted session was restored at start-up: provision/load the profile.
    scheduleMicrotask(() => _ensure(userId));
    return AuthState.provisioning(userId, email: _gateway.currentEmail);
  }

  void _onEvent(AuthEvent event) {
    switch (event.type) {
      case AuthEventType.signedOut:
        if (state.phase != AuthPhase.signedOut &&
            state.phase != AuthPhase.awaitingConfirmation) {
          _toSignedOut();
        }
      case AuthEventType.initialSession:
      case AuthEventType.signedIn:
      case AuthEventType.tokenRefreshed:
      case AuthEventType.userUpdated:
        final userId = event.userId;
        if (userId != null && userId != state.userId) {
          // A different identity: drop everything belonging to the old one.
          _ensure(userId);
        }
      case AuthEventType.other:
        break;
    }
  }

  /// Provisions [userId] unless that is already done or in progress.
  Future<void> _ensure(String userId) {
    if (_inflightFor == userId && _inflight != null) return _inflight!;
    if (state.userId == userId && state.phase == AuthPhase.signedIn) {
      return Future.value();
    }
    return _establish(userId);
  }

  Future<void> _establish(String userId) {
    final email = _gateway.currentEmail;
    state = AuthState.provisioning(userId, email: email);
    _inflightFor = userId;
    final future = () async {
      try {
        final api = ref.read(apiServiceProvider);
        await api.provision(fullName: _gateway.currentFullNameHint);
        if (!ref.mounted) return;
        final user = await api.getCurrentUser();
        if (!ref.mounted) return;
        if (state.userId == userId) {
          state = AuthState.signedIn(user);
          ref.read(monitoringProvider).identify(user.id);
        }
      } catch (e) {
        if (!ref.mounted) return;
        if (state.userId == userId && state.phase == AuthPhase.provisioning) {
          final error = ApiError.from(e) ??
              const ApiError(statusCode: null, code: 'unknown', detail: 'Could not load your profile.');
          state = AuthState.provisioningFailed(userId, error, email: email);
        }
      } finally {
        if (_inflightFor == userId) {
          _inflight = null;
          _inflightFor = null;
        }
      }
    }();
    _inflight = future;
    return future;
  }

  void _toSignedOut() {
    _inflight = null;
    _inflightFor = null;
    state = const AuthState.signedOut();
    ref.read(monitoringProvider).resetIdentity();
  }

  /// Signs in with Supabase, then provisions and loads the profile.
  /// Throws [AuthFailure] with a presentable message.
  Future<void> signIn({required String email, required String password}) async {
    await _gateway.signIn(email: email, password: password);
    final userId = _gateway.currentUserId;
    if (userId == null) throw const AuthFailure('Sign-in did not return a session.');
    await _ensure(userId);
    ref.read(monitoringProvider).capture('login');
  }

  /// Signs up. With email confirmation disabled Supabase returns a session and
  /// the profile is provisioned straight away; otherwise the user is asked to
  /// confirm their email first.
  Future<void> signUp({
    required String email,
    required String password,
    required String fullName,
  }) async {
    final outcome = await _gateway.signUp(email: email, password: password, fullName: fullName);
    final userId = _gateway.currentUserId;
    if (outcome.hasSession && userId != null) {
      await _ensure(userId);
    } else {
      state = AuthState.awaitingConfirmation(email);
    }
    ref.read(monitoringProvider).capture('sign_up');
  }

  Future<void> resendConfirmation() async {
    final email = state.email;
    if (email == null) return;
    await _gateway.resendConfirmation(email);
  }

  /// Leaves the "check your email" screen.
  void backToSignIn() {
    if (state.phase == AuthPhase.awaitingConfirmation) {
      state = const AuthState.signedOut();
    }
  }

  /// Retries provisioning after a failure.
  Future<void> retryProvisioning() async {
    final userId = state.userId ?? _gateway.currentUserId;
    if (userId == null) return _toSignedOut();
    await _establish(userId);
  }

  /// Replaces the loaded profile (after an edit).
  void profileUpdated(User user) {
    if (state.isSignedIn && state.userId == user.id) state = AuthState.signedIn(user);
  }

  /// Ends the Supabase session and clears all user-scoped state.
  Future<void> signOut() async {
    try {
      await _gateway.signOut();
    } catch (_) {
      // Local clean-up proceeds even if the network call fails.
    }
    _toSignedOut();
  }

  /// Called by the API client when a refresh fails: the session is over.
  Future<void> sessionExpired() => signOut();
}

final authControllerProvider =
    NotifierProvider<AuthController, AuthState>(AuthController.new);
