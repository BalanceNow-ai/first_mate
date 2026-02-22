import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_provider.dart';
import 'package:helm_marine/features/auth/screens/login_screen.dart';
import 'package:helm_marine/features/auth/screens/signup_screen.dart';
import 'package:helm_marine/features/home/screens/home_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_list_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_detail_screen.dart';
import 'package:helm_marine/features/vessels/screens/vessel_form_screen.dart';
import 'package:helm_marine/features/products/screens/product_list_screen.dart';
import 'package:helm_marine/features/products/screens/product_detail_screen.dart';
import 'package:helm_marine/features/ai_chat/screens/chat_screen.dart';
import 'package:helm_marine/features/loyalty/screens/crew_dashboard_screen.dart';
import 'package:helm_marine/features/helm_dash/screens/delivery_tracking_screen.dart';
import 'package:helm_marine/features/checklists/screens/vessel_checklists_screen.dart';
import 'package:helm_marine/features/checkout/screens/checkout_screen.dart';
import 'package:helm_marine/features/checkout/screens/order_detail_screen.dart';
import 'package:helm_marine/features/profile/screens/user_profile_screen.dart';
import 'package:helm_marine/features/profile/screens/edit_profile_screen.dart';
import 'package:helm_marine/features/onboarding/screens/onboarding_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authStateProvider);

  return GoRouter(
    initialLocation: '/login',
    redirect: (context, state) {
      final isLoggedIn = authState.valueOrNull != null;
      final isAuthRoute =
          state.matchedLocation == '/login' || state.matchedLocation == '/signup';
      final isOnboarding = state.matchedLocation == '/onboarding';

      if (!isLoggedIn && !isAuthRoute && !isOnboarding) return '/login';
      if (isLoggedIn && isAuthRoute) return '/';
      return null;
    },
    routes: [
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),
      GoRoute(
        path: '/signup',
        builder: (context, state) => const SignupScreen(),
      ),
      GoRoute(
        path: '/onboarding',
        builder: (context, state) => const OnboardingScreen(),
      ),
      ShellRoute(
        builder: (context, state, child) => _ScaffoldWithNav(child: child),
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) => const HomeScreen(),
          ),
          GoRoute(
            path: '/vessels',
            builder: (context, state) => const VesselListScreen(),
            routes: [
              GoRoute(
                path: 'new',
                builder: (context, state) {
                  final from = state.uri.queryParameters['from'];
                  return VesselFormScreen(fromOnboarding: from == 'onboarding');
                },
              ),
              GoRoute(
                path: ':vesselId',
                builder: (context, state) => VesselDetailScreen(
                  vesselId: state.pathParameters['vesselId']!,
                ),
                routes: [
                  GoRoute(
                    path: 'edit',
                    builder: (context, state) => VesselFormScreen(
                      vesselId: state.pathParameters['vesselId'],
                    ),
                  ),
                  GoRoute(
                    path: 'chat',
                    builder: (context, state) => ChatScreen(
                      vesselId: state.pathParameters['vesselId'],
                    ),
                  ),
                  GoRoute(
                    path: 'checklists',
                    builder: (context, state) => VesselChecklistsScreen(
                      vesselId: state.pathParameters['vesselId']!,
                    ),
                  ),
                ],
              ),
            ],
          ),
          GoRoute(
            path: '/products',
            builder: (context, state) => const ProductListScreen(),
            routes: [
              GoRoute(
                path: ':productId',
                builder: (context, state) => ProductDetailScreen(
                  productId: state.pathParameters['productId']!,
                ),
              ),
            ],
          ),
          GoRoute(
            path: '/crew',
            builder: (context, state) => const CrewDashboardScreen(),
          ),
          GoRoute(
            path: '/chat',
            builder: (context, state) => const ChatScreen(),
          ),
          GoRoute(
            path: '/dash/:deliveryId',
            builder: (context, state) => DeliveryTrackingScreen(
              deliveryId: state.pathParameters['deliveryId']!,
            ),
          ),
          GoRoute(
            path: '/checkout',
            builder: (context, state) => const CheckoutScreen(),
          ),
          GoRoute(
            path: '/orders/:orderId',
            builder: (context, state) => OrderDetailScreen(
              orderId: state.pathParameters['orderId']!,
            ),
          ),
          GoRoute(
            path: '/profile',
            builder: (context, state) => const UserProfileScreen(),
            routes: [
              GoRoute(
                path: 'edit',
                builder: (context, state) => const EditProfileScreen(),
              ),
            ],
          ),
        ],
      ),
    ],
  );
});

class _ScaffoldWithNav extends StatelessWidget {
  final Widget child;

  const _ScaffoldWithNav({required this.child});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _calculateSelectedIndex(context),
        onDestinationSelected: (index) => _onItemTapped(index, context),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home), label: 'Home'),
          NavigationDestination(icon: Icon(Icons.directions_boat), label: 'Vessels'),
          NavigationDestination(icon: Icon(Icons.shopping_bag), label: 'Products'),
          NavigationDestination(icon: Icon(Icons.stars), label: 'Crew'),
          NavigationDestination(icon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }

  int _calculateSelectedIndex(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    if (location.startsWith('/vessels')) return 1;
    if (location.startsWith('/products')) return 2;
    if (location.startsWith('/crew')) return 3;
    if (location.startsWith('/profile')) return 4;
    return 0;
  }

  void _onItemTapped(int index, BuildContext context) {
    switch (index) {
      case 0:
        context.go('/');
      case 1:
        context.go('/vessels');
      case 2:
        context.go('/products');
      case 3:
        context.go('/crew');
      case 4:
        context.go('/profile');
    }
  }
}
