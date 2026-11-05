import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/routes/catalogue_routes.dart';
import 'package:helm_marine/core/routes/commerce_routes.dart';
import 'package:helm_marine/core/routes/engagement_routes.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/widgets/app_shell.dart';
import 'package:helm_marine/features/ai_chat/screens/chat_screen.dart';
import 'package:helm_marine/features/auth/screens/check_email_screen.dart';
import 'package:helm_marine/features/auth/screens/login_screen.dart';
import 'package:helm_marine/features/auth/screens/provisioning_screen.dart';
import 'package:helm_marine/features/auth/screens/signup_screen.dart';
import 'package:helm_marine/features/cart/screens/cart_screen.dart';
import 'package:helm_marine/features/checklists/screens/vessel_checklists_screen.dart';
import 'package:helm_marine/features/checkout/screens/checkout_screen.dart';
import 'package:helm_marine/features/checkout/screens/order_detail_screen.dart';
import 'package:helm_marine/features/helm_dash/screens/delivery_tracking_screen.dart';
import 'package:helm_marine/features/home/screens/home_screen.dart';
import 'package:helm_marine/features/loyalty/screens/crew_dashboard_screen.dart';
import 'package:helm_marine/features/onboarding/screens/onboarding_screen.dart';
import 'package:helm_marine/features/products/screens/product_detail_screen.dart';
import 'package:helm_marine/features/products/screens/product_list_screen.dart';
import 'package:helm_marine/features/profile/screens/edit_profile_screen.dart';
import 'package:helm_marine/features/profile/screens/user_profile_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_detail_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_form_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_list_screen.dart';

const _signedOutRoutes = {'/login', '/signup'};
const _flowRoutes = {'/login', '/signup', '/check-email', '/provisioning'};

/// Where the auth state sends a navigation to [location] (`null` = allow).
///
/// * signed out → `/login` (remembering the requested page in `from`)
/// * awaiting email confirmation → `/check-email`
/// * session but profile not provisioned (or failed) → `/provisioning`
/// * signed in on an auth page → the remembered page or `/`
String? authRedirect(AuthState auth, Uri uri) {
  final location = uri.path;
  switch (auth.phase) {
    case AuthPhase.signedOut:
      if (_signedOutRoutes.contains(location)) return null;
      if (location == '/' || _flowRoutes.contains(location)) return '/login';
      return Uri(path: '/login', queryParameters: {'from': uri.toString()}).toString();
    case AuthPhase.awaitingConfirmation:
      return location == '/check-email' ? null : '/check-email';
    case AuthPhase.provisioning:
    case AuthPhase.provisioningFailed:
      if (location == '/provisioning') return null;
      // Keep the page a restored session was opened on (e.g. after a reload).
      final from = uri.queryParameters['from'] ??
          (location == '/' || _flowRoutes.contains(location) ? null : uri.toString());
      return Uri(path: '/provisioning', queryParameters: from == null ? null : {'from': from})
          .toString();
    case AuthPhase.signedIn:
      if (!_flowRoutes.contains(location)) return null;
      final from = uri.queryParameters['from'];
      if (from != null && from.startsWith('/') && !from.startsWith('//')) return from;
      return '/';
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.listen(authControllerProvider, (_, _) => refresh.value++);

  final router = GoRouter(
    initialLocation: '/',
    refreshListenable: refresh,
    redirect: (context, state) => authRedirect(ref.read(authControllerProvider), state.uri),
    routes: [
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(path: '/signup', builder: (context, state) => const SignupScreen()),
      GoRoute(path: '/check-email', builder: (context, state) => const CheckEmailScreen()),
      GoRoute(path: '/provisioning', builder: (context, state) => const ProvisioningScreen()),
      GoRoute(path: '/onboarding', builder: (context, state) => const OnboardingScreen()),
      ShellRoute(
        builder: (context, state, child) => AppShell(child: child),
        routes: [
          GoRoute(path: '/', builder: (context, state) => const HomeScreen()),
          GoRoute(
            path: '/vessels',
            builder: (context, state) => const VesselListScreen(),
            routes: [
              GoRoute(
                path: 'new',
                builder: (context, state) => VesselFormScreen(
                  fromOnboarding: state.uri.queryParameters['from'] == 'onboarding',
                ),
              ),
              GoRoute(
                path: ':vesselId',
                builder: (context, state) =>
                    VesselDetailScreen(vesselId: state.pathParameters['vesselId']!),
                routes: [
                  GoRoute(
                    path: 'edit',
                    builder: (context, state) =>
                        VesselFormScreen(vesselId: state.pathParameters['vesselId']),
                  ),
                  GoRoute(
                    path: 'chat',
                    builder: (context, state) =>
                        ChatScreen(vesselId: state.pathParameters['vesselId']),
                  ),
                  GoRoute(
                    path: 'checklists',
                    builder: (context, state) =>
                        VesselChecklistsScreen(vesselId: state.pathParameters['vesselId']!),
                  ),
                ],
              ),
            ],
          ),
          GoRoute(
            path: '/products',
            builder: (context, state) =>
                ProductListScreen(initialParams: state.uri.queryParameters),
            routes: [
              GoRoute(
                path: ':productId',
                builder: (context, state) =>
                    ProductDetailScreen(productId: state.pathParameters['productId']!),
              ),
            ],
          ),
          GoRoute(path: '/cart', builder: (context, state) => const CartScreen()),
          GoRoute(path: '/crew', builder: (context, state) => const CrewDashboardScreen()),
          GoRoute(path: '/chat', builder: (context, state) => const ChatScreen()),
          GoRoute(
            path: '/dash/:deliveryId',
            builder: (context, state) =>
                DeliveryTrackingScreen(deliveryId: state.pathParameters['deliveryId']!),
          ),
          GoRoute(path: '/checkout', builder: (context, state) => const CheckoutScreen()),
          GoRoute(
            path: '/orders/:orderId',
            builder: (context, state) =>
                OrderDetailScreen(orderId: state.pathParameters['orderId']!),
          ),
          GoRoute(
            path: '/profile',
            builder: (context, state) => const UserProfileScreen(),
            routes: [
              GoRoute(path: 'edit', builder: (context, state) => const EditProfileScreen()),
            ],
          ),
          ...catalogueRoutes,
          ...commerceRoutes,
          ...engagementRoutes,
        ],
      ),
    ],
  );
  ref.onDispose(() {
    router.dispose();
    refresh.dispose();
  });
  return router;
});
