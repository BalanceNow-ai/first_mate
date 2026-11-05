import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/profile/providers/profile_provider.dart';

class UserProfileScreen extends ConsumerStatefulWidget {
  const UserProfileScreen({super.key});

  @override
  ConsumerState<UserProfileScreen> createState() => _UserProfileScreenState();
}

class _UserProfileScreenState extends ConsumerState<UserProfileScreen> {
  @override
  Widget build(BuildContext context) {
    final authState = AsyncValue<User?>.data(ref.watch(currentUserProvider));
    final ordersState = ref.watch(orderHistoryProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // --- User Details ---
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: authState.when(
                data: (user) {
                  if (user == null) {
                    return const Text('Not logged in');
                  }
                  return Column(
                    children: [
                      CircleAvatar(
                        radius: 36,
                        backgroundColor: HelmTheme.primary.withValues(alpha: 0.1),
                        child: Text(
                          (user.fullName ?? user.email)
                              .substring(0, 1)
                              .toUpperCase(),
                          style: const TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                            color: HelmTheme.primary,
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        user.fullName ?? 'No name set',
                        style: Theme.of(context)
                            .textTheme
                            .titleLarge
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        user.email,
                        style: TextStyle(color: Colors.grey[600]),
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: () => context.go('/profile/edit'),
                          icon: const Icon(Icons.edit, size: 18),
                          label: const Text('Edit Profile'),
                        ),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: () async {
                            // The router returns to /login once signed out.
                            await ref.read(authControllerProvider.notifier).signOut();
                          },
                          icon: const Icon(Icons.logout, size: 18),
                          label: const Text('Log Out'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: HelmTheme.error,
                          ),
                        ),
                      ),
                    ],
                  );
                },
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Text('Error: $e'),
              ),
            ),
          ),
          const SizedBox(height: 24),

          // --- Order History ---
          Text(
            'Order History',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          ordersState.when(
            data: (orders) {
              if (orders.isEmpty) {
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      children: [
                        Icon(Icons.receipt_long,
                            size: 48,
                            color: Colors.grey[300]),
                        const SizedBox(height: 8),
                        Text(
                          'No orders yet',
                          style: TextStyle(color: Colors.grey[500]),
                        ),
                      ],
                    ),
                  ),
                );
              }
              return Column(
                children: orders.map((order) {
                  final orderId = order['id']?.toString() ?? '';
                  final status = order['status'] as String? ?? '';
                  final total = order['total_cents'] as int? ?? 0;
                  final createdAt = order['created_at'] as String? ?? '';

                  String dateStr = '';
                  if (createdAt.isNotEmpty) {
                    try {
                      final dt = DateTime.parse(createdAt);
                      dateStr = '${dt.day}/${dt.month}/${dt.year}';
                    } catch (_) {}
                  }

                  return Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      onTap: () => context.go('/orders/$orderId'),
                      leading: _statusIcon(status),
                      title: Text(
                        'Order #${orderId.length >= 8 ? orderId.substring(0, 8).toUpperCase() : orderId}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      subtitle: Text(dateStr.isNotEmpty
                          ? '$dateStr — ${status.toUpperCase()}'
                          : status.toUpperCase()),
                      trailing: Text(
                        formatCents(total),
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          color: HelmTheme.primary,
                        ),
                      ),
                    ),
                  );
                }).toList(),
              );
            },
            loading: () =>
                const Center(child: CircularProgressIndicator()),
            error: (e, _) => Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text('Failed to load orders: $e'),
              ),
            ),
          ),
          const SizedBox(height: 24),

          // --- Settings ---
          Text(
            'Settings',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              title: const Text('Notification preferences'),
              subtitle: const Text('Email, push, order, delivery and service updates'),
              leading: const Icon(Icons.notifications_outlined),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.go('/profile/notifications'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _statusIcon(String status) {
    IconData icon;
    Color color;
    switch (status) {
      case 'paid':
        icon = Icons.check_circle;
        color = HelmTheme.success;
      case 'shipped':
        icon = Icons.local_shipping;
        color = HelmTheme.accent;
      case 'delivered':
        icon = Icons.done_all;
        color = HelmTheme.success;
      case 'cancelled':
        icon = Icons.cancel;
        color = HelmTheme.error;
      default:
        icon = Icons.pending;
        color = Colors.grey;
    }
    return Icon(icon, color: color);
  }
}
