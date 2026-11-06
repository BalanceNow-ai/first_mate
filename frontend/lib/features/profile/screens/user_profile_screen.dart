import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/auth/auth_controller.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/orders/screens/orders_screens.dart';
import 'package:helm_marine/features/invoices/widgets/invoices_entry.dart';
import 'package:helm_marine/features/moderation/screens/moderation_screens.dart';
import 'package:helm_marine/features/service_jobs/widgets/service_menu_entries.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_hub_screen.dart';

class UserProfileScreen extends ConsumerStatefulWidget {
  const UserProfileScreen({super.key});

  @override
  ConsumerState<UserProfileScreen> createState() => _UserProfileScreenState();
}

class _UserProfileScreenState extends ConsumerState<UserProfileScreen> {
  @override
  Widget build(BuildContext context) {
    final authState = AsyncValue<User?>.data(ref.watch(currentUserProvider));

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
          const RecentOrdersSection(),
          const StaffToolsEntry(),
          const InvoicesEntry(),
          const SizedBox(height: 12),
          const ServiceMenuEntries(),
          const ModerationEntry(),
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
}
