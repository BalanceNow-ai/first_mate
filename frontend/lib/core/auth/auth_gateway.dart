import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as supa;

/// What kind of change Supabase reported.
enum AuthEventType { initialSession, signedIn, signedOut, tokenRefreshed, userUpdated, other }

/// A session change, decoupled from the Supabase SDK types.
class AuthEvent {
  const AuthEvent(this.type, {this.userId, this.email});

  final AuthEventType type;

  /// Subject (`sub`) of the session after the event, or null when signed out.
  final String? userId;
  final String? email;
}

/// Result of a sign-up call.
class SignUpOutcome {
  const SignUpOutcome({required this.hasSession, this.userId});

  /// True when Supabase returned a session (email confirmation disabled).
  final bool hasSession;
  final String? userId;
}

/// A sign-in / sign-up failure with a message safe to show.
class AuthFailure implements Exception {
  const AuthFailure(this.message, {this.code});

  final String message;
  final String? code;

  @override
  String toString() => message;
}

/// The identity provider seen by the app. Production uses Supabase Auth; tests
/// substitute a fake. The API layer never stores token copies: it asks this
/// gateway for the *current* access token on every request.
abstract class AuthGateway {
  /// Access token of the current (persisted) session, or null.
  String? get currentAccessToken;

  /// Subject of the current session, or null.
  String? get currentUserId;

  String? get currentEmail;

  /// `full_name` the user entered at sign-up (from user metadata), if any.
  String? get currentFullNameHint;

  /// Session changes, including the restored session on start-up.
  Stream<AuthEvent> get events;

  Future<SignUpOutcome> signUp({
    required String email,
    required String password,
    required String fullName,
  });

  Future<void> signIn({required String email, required String password});

  Future<void> resendConfirmation(String email);

  /// Refreshes the session; returns the new access token or null on failure.
  Future<String?> refreshSession();

  Future<void> signOut();
}

/// [AuthGateway] backed by `Supabase.instance.client.auth`.
class SupabaseAuthGateway implements AuthGateway {
  SupabaseAuthGateway(this._auth);

  final supa.GoTrueClient _auth;

  @override
  String? get currentAccessToken => _auth.currentSession?.accessToken;

  @override
  String? get currentUserId => _auth.currentSession?.user.id;

  @override
  String? get currentEmail => _auth.currentSession?.user.email;

  @override
  String? get currentFullNameHint {
    final value = _auth.currentUser?.userMetadata?['full_name'];
    return value is String && value.trim().isNotEmpty ? value.trim() : null;
  }

  @override
  Stream<AuthEvent> get events => _auth.onAuthStateChange.map((state) {
        final session = state.session;
        final type = switch (state.event) {
          supa.AuthChangeEvent.initialSession => AuthEventType.initialSession,
          supa.AuthChangeEvent.signedIn => AuthEventType.signedIn,
          supa.AuthChangeEvent.signedOut => AuthEventType.signedOut,
          supa.AuthChangeEvent.tokenRefreshed => AuthEventType.tokenRefreshed,
          supa.AuthChangeEvent.userUpdated => AuthEventType.userUpdated,
          _ => AuthEventType.other,
        };
        return AuthEvent(type, userId: session?.user.id, email: session?.user.email);
      });

  @override
  Future<SignUpOutcome> signUp({
    required String email,
    required String password,
    required String fullName,
  }) async {
    try {
      final res = await _auth.signUp(
        email: email,
        password: password,
        data: {'full_name': fullName},
      );
      return SignUpOutcome(hasSession: res.session != null, userId: res.user?.id);
    } on supa.AuthException catch (e) {
      throw AuthFailure(e.message, code: e.code);
    }
  }

  @override
  Future<void> signIn({required String email, required String password}) async {
    try {
      final res = await _auth.signInWithPassword(email: email, password: password);
      if (res.session == null) {
        throw const AuthFailure('Sign-in did not return a session.');
      }
    } on supa.AuthException catch (e) {
      throw AuthFailure(e.message, code: e.code);
    }
  }

  @override
  Future<void> resendConfirmation(String email) async {
    try {
      await _auth.resend(type: supa.OtpType.signup, email: email);
    } on supa.AuthException catch (e) {
      throw AuthFailure(e.message, code: e.code);
    }
  }

  @override
  Future<String?> refreshSession() async {
    try {
      final res = await _auth.refreshSession();
      return res.session?.accessToken;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> signOut() => _auth.signOut();
}

/// The app's [AuthGateway]. Overridden in `main()` with the Supabase gateway.
final authGatewayProvider = Provider<AuthGateway>(
  (ref) => throw UnimplementedError('authGatewayProvider must be overridden'),
);
