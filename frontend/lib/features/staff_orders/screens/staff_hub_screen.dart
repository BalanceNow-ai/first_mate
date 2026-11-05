import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_common.dart';

const staffRoles = {'operator', 'dispatcher', 'admin'};

/// Entry to the staff tools from the profile (staff roles only).
class StaffToolsEntry extends ConsumerWidget {
  const StaffToolsEntry({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(currentUserProvider)?.role;
    if (role == null || !staffRoles.contains(role)) return const SizedBox.shrink();
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: ListTile(
        leading: const Icon(Icons.admin_panel_settings),
        title: const Text('Staff tools'),
        subtitle: Text('Signed in as $role'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.go('/staff'),
      ),
    );
  }
}

class _Tool {
  const _Tool(this.path, this.title, this.subtitle, this.icon, this.roles);

  final String path;
  final String title;
  final String subtitle;
  final IconData icon;
  final Set<String> roles;
}

const _tools = [
  _Tool('/staff/dispatch', 'Dispatch console', 'Helm Dash deliveries, assignment, cancel / fail', Icons.map, {'dispatcher'}),
  _Tool('/staff/orders', 'Staff orders', 'All orders, fulfilment, courier test labels, refunds', Icons.inventory_2,
      {'dispatcher'}),
  _Tool('/staff/operator', 'Operator jobs', 'Availability, my jobs, status and position reports', Icons.sailing,
      {'operator'}),
  _Tool('/staff/admin', 'Helm Dash admin', 'Operating areas, operators, payouts, reconciliation',
      Icons.admin_panel_settings, {'admin'}),
];

/// `/staff`: the tools this account's role can use.
class StaffHubScreen extends ConsumerWidget {
  const StaffHubScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RoleGate(
      roles: const {'operator', 'dispatcher'},
      title: 'Staff tools',
      builder: (context, me) => Scaffold(
        appBar: AppBar(title: const Text('Staff tools')),
        body: ContentWidth(
          maxWidth: 820,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('Signed in as ${me.email} (${me.role})'),
              const SizedBox(height: 8),
              for (final t in _tools)
                if (roleAllows(me.role, t.roles))
                  Card(
                    child: ListTile(
                      leading: Icon(t.icon),
                      title: Text(t.title),
                      subtitle: Text(t.subtitle),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => context.go(t.path),
                    ),
                  ),
            ],
          ),
        ),
      ),
    );
  }
}
