import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/dispatch/screens/admin_screens.dart';
import 'package:helm_marine/features/dispatch/screens/dispatcher_screens.dart';
import 'package:helm_marine/features/dispatch/screens/operator_screens.dart';
import 'package:helm_marine/features/orders/screens/orders_screens.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_hub_screen.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_orders_screens.dart';

/// Additional in-shell routes owned by the commerce client workstream.
/// (`/checkout`, `/orders/:orderId` and `/dash/:deliveryId` stay in router.dart.)
final List<RouteBase> commerceRoutes = <RouteBase>[
  GoRoute(path: '/orders', builder: (context, state) => const OrdersScreen()),
  GoRoute(
    path: '/orders/:orderId/pay',
    builder: (context, state) => OrderPaymentScreen(orderId: state.pathParameters['orderId']!),
  ),
  GoRoute(
    path: '/staff',
    builder: (context, state) => const StaffHubScreen(),
    routes: [
      GoRoute(
        path: 'dispatch',
        builder: (context, state) => const DispatchConsoleScreen(),
        routes: [
          GoRoute(
            path: ':deliveryId',
            builder: (context, state) => DispatchDeliveryScreen(deliveryId: state.pathParameters['deliveryId']!),
          ),
        ],
      ),
      GoRoute(
        path: 'operator',
        builder: (context, state) => const OperatorHomeScreen(),
        routes: [
          GoRoute(
            path: 'jobs/:deliveryId',
            builder: (context, state) => OperatorJobScreen(deliveryId: state.pathParameters['deliveryId']!),
          ),
        ],
      ),
      GoRoute(
        path: 'orders',
        builder: (context, state) => const StaffOrdersScreen(),
        routes: [
          GoRoute(
            path: ':orderId',
            builder: (context, state) => StaffOrderDetailScreen(orderId: state.pathParameters['orderId']!),
          ),
        ],
      ),
      GoRoute(path: 'admin', builder: (context, state) => const HelmDashAdminScreen()),
    ],
  ),
];
