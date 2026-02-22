import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/models/user.dart';

const _storage = FlutterSecureStorage();

/// Provides the current authenticated user, or null if not logged in.
final authStateProvider =
    AsyncNotifierProvider<AuthNotifier, User?>(AuthNotifier.new);

class AuthNotifier extends AsyncNotifier<User?> {
  @override
  Future<User?> build() async {
    final token = await _storage.read(key: 'access_token');
    if (token == null) return null;

    try {
      final apiService = ref.read(apiServiceProvider);
      return await apiService.getCurrentUser();
    } catch (_) {
      // Token invalid / expired — clear it
      await _storage.delete(key: 'access_token');
      return null;
    }
  }

  Future<void> signIn({required String email, required String password}) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final supabase = Supabase.instance.client;
      final response = await supabase.auth.signInWithPassword(
        email: email,
        password: password,
      );

      final session = response.session;
      if (session == null) {
        throw Exception('Sign-in failed: no session returned');
      }

      await setTokens(
        accessToken: session.accessToken,
        refreshToken: session.refreshToken,
      );

      final apiService = ref.read(apiServiceProvider);
      return await apiService.getCurrentUser();
    });
  }

  Future<void> signUp({
    required String email,
    required String password,
    required String fullName,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final supabase = Supabase.instance.client;
      final response = await supabase.auth.signUp(
        email: email,
        password: password,
        data: {'full_name': fullName},
      );

      final session = response.session;
      if (session != null) {
        await setTokens(
          accessToken: session.accessToken,
          refreshToken: session.refreshToken,
        );
      }

      final apiService = ref.read(apiServiceProvider);
      final user = await apiService.registerUser({
        'email': email,
        'full_name': fullName,
      });
      return user;
    });
  }

  Future<void> signOut() async {
    try {
      await Supabase.instance.client.auth.signOut();
    } catch (_) {
      // Continue with local cleanup even if Supabase signout fails
    }
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
    state = const AsyncData(null);
  }

  Future<void> setTokens({
    required String accessToken,
    String? refreshToken,
  }) async {
    await _storage.write(key: 'access_token', value: accessToken);
    if (refreshToken != null) {
      await _storage.write(key: 'refresh_token', value: refreshToken);
    }
    ref.invalidateSelf();
  }
}
