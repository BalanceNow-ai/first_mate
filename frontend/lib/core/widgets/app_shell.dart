import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';

class _Destination {
  const _Destination(this.path, this.label, this.icon, this.selectedIcon);

  final String path;
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

const _destinations = [
  _Destination('/', 'Home', Icons.home_outlined, Icons.home),
  _Destination('/vessels', 'Vessels', Icons.directions_boat_outlined, Icons.directions_boat),
  _Destination('/products', 'Shop', Icons.storefront_outlined, Icons.storefront),
  _Destination('/cart', 'Cart', Icons.shopping_cart_outlined, Icons.shopping_cart),
  _Destination('/profile', 'Account', Icons.person_outline, Icons.person),
];

/// Width at which navigation moves from a bottom bar to a side rail.
const wideLayoutBreakpoint = 840.0;

/// Signed-in chrome: bottom navigation on phones, a navigation rail on wide
/// (tablet / web / desktop) layouts, plus a banner when the API is unreachable.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  int _selectedIndex(String location) {
    for (var i = _destinations.length - 1; i > 0; i--) {
      if (location.startsWith(_destinations[i].path)) return i;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final location = GoRouterState.of(context).uri.path;
    final selected = _selectedIndex(location);
    final cartCount = ref.watch(cartProvider.select((c) => c.value?.itemCount ?? 0));
    final config = ref.watch(publicConfigProvider);
    final wide = MediaQuery.sizeOf(context).width >= wideLayoutBreakpoint;

    Widget icon(_Destination d, bool isSelected) {
      final base = Icon(isSelected ? d.selectedIcon : d.icon);
      if (d.path != '/cart' || cartCount == 0) return base;
      return Badge(label: Text('$cartCount'), child: base);
    }

    String semanticLabel(_Destination d) =>
        d.path == '/cart' && cartCount > 0 ? 'Cart, $cartCount items' : d.label;

    final body = Column(
      children: [
        if (config.hasError)
          _ConnectivityBanner(
            message: describeError(config.error!),
            onRetry: () => ref.invalidate(publicConfigProvider),
          ),
        Expanded(child: child),
      ],
    );

    if (wide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: selected,
              labelType: NavigationRailLabelType.all,
              onDestinationSelected: (i) => context.go(_destinations[i].path),
              leading: const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Icon(Icons.sailing, color: HelmTheme.navy, size: 32, semanticLabel: 'Helm'),
              ),
              destinations: [
                for (final (i, d) in _destinations.indexed)
                  NavigationRailDestination(
                    icon: Semantics(label: semanticLabel(d), child: icon(d, false)),
                    selectedIcon: icon(d, i == selected),
                    label: Text(d.label),
                  ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: body),
          ],
        ),
      );
    }
    return Scaffold(
      body: body,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selected,
        onDestinationSelected: (i) => context.go(_destinations[i].path),
        destinations: [
          for (final (i, d) in _destinations.indexed)
            NavigationDestination(
              icon: icon(d, false),
              selectedIcon: icon(d, i == selected),
              label: d.label,
              tooltip: semanticLabel(d),
            ),
        ],
      ),
    );
  }
}

class _ConnectivityBanner extends StatelessWidget {
  const _ConnectivityBanner({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: HelmTheme.warning.withValues(alpha: 0.15),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Row(
            children: [
              const Icon(Icons.cloud_off, color: HelmTheme.warning),
              const SizedBox(width: 12),
              Expanded(child: Text(message)),
              TextButton(onPressed: onRetry, child: const Text('Retry')),
            ],
          ),
        ),
      ),
    );
  }
}
