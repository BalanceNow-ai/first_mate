import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/helm_dash/providers/delivery_provider.dart';

class DeliveryTrackingScreen extends ConsumerWidget {
  final String deliveryId;

  const DeliveryTrackingScreen({super.key, required this.deliveryId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deliveryState = ref.watch(deliveryDetailProvider(deliveryId));
    final liveLocationState =
        ref.watch(deliveryLiveLocationProvider(deliveryId));

    return Scaffold(
      appBar: AppBar(title: const Text('Delivery Tracking')),
      body: deliveryState.when(
        data: (delivery) {
          final status = delivery['status'] as String? ?? 'pending';
          final nm =
              (delivery['nautical_miles'] as num?)?.toDouble();
          final fee =
              (delivery['delivery_fee'] as num?)?.toDouble() ?? 0;
          final etaMinutes =
              delivery['estimated_delivery_minutes'] as int?;
          final operatorName = delivery['operator_name'] as String?;
          final locationName =
              delivery['delivery_location_name'] as String?;
          final coords =
              delivery['delivery_coordinates'] as Map<String, dynamic>?;

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Map placeholder
              Container(
                height: 250,
                decoration: BoxDecoration(
                  color: HelmTheme.primary.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(16),
                  border:
                      Border.all(color: HelmTheme.primary.withOpacity(0.2)),
                ),
                child: Stack(
                  children: [
                    // Simulated map area
                    const Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.map, size: 48, color: HelmTheme.primary),
                          SizedBox(height: 8),
                          Text(
                            'Mapbox map view',
                            style: TextStyle(color: HelmTheme.primary),
                          ),
                          Text(
                            '(Requires Mapbox access token)',
                            style:
                                TextStyle(color: Colors.grey, fontSize: 12),
                          ),
                        ],
                      ),
                    ),

                    // Warehouse pin
                    const Positioned(
                      left: 30,
                      top: 40,
                      child: _MapPin(
                        icon: Icons.warehouse,
                        color: HelmTheme.primary,
                        label: 'Warehouse',
                      ),
                    ),

                    // Delivery pin
                    if (coords != null)
                      const Positioned(
                        right: 40,
                        bottom: 50,
                        child: _MapPin(
                          icon: Icons.location_on,
                          color: HelmTheme.error,
                          label: 'Delivery',
                        ),
                      ),

                    // Live vessel position
                    liveLocationState.whenOrNull(
                          data: (loc) => Positioned(
                            left: _simulateX(status),
                            top: _simulateY(status),
                            child: _MapPin(
                              icon: Icons.directions_boat,
                              color: HelmTheme.accent,
                              label: loc.label,
                            ),
                          ),
                        ) ??
                        const SizedBox.shrink(),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // Status
              _StatusBanner(status: status),
              const SizedBox(height: 16),

              // Delivery details
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Delivery Details',
                        style: Theme.of(context)
                            .textTheme
                            .titleSmall
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const Divider(),
                      if (locationName != null)
                        _DetailRow(
                          icon: Icons.location_on,
                          label: 'Destination',
                          value: locationName,
                        ),
                      if (nm != null)
                        _DetailRow(
                          icon: Icons.straighten,
                          label: 'Distance',
                          value: '${nm.toStringAsFixed(1)} NM',
                        ),
                      _DetailRow(
                        icon: Icons.attach_money,
                        label: 'Delivery Fee',
                        value: '\$${fee.toStringAsFixed(2)} NZD',
                      ),
                      if (etaMinutes != null)
                        _DetailRow(
                          icon: Icons.timer,
                          label: 'Estimated Time',
                          value: etaMinutes >= 60
                              ? '${etaMinutes ~/ 60}h ${etaMinutes % 60}m'
                              : '$etaMinutes min',
                        ),
                      if (operatorName != null)
                        _DetailRow(
                          icon: Icons.person,
                          label: 'Operator',
                          value: operatorName,
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // Status timeline
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Status Timeline',
                        style: Theme.of(context)
                            .textTheme
                            .titleSmall
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 12),
                      _TimelineStep(
                        label: 'Order Placed',
                        isComplete: true,
                        isActive: status == 'pending',
                      ),
                      _TimelineStep(
                        label: 'Assigned to Operator',
                        isComplete: _statusIndex(status) >= 1,
                        isActive: status == 'assigned',
                      ),
                      _TimelineStep(
                        label: 'Picking Up',
                        isComplete: _statusIndex(status) >= 2,
                        isActive: status == 'pickup',
                      ),
                      _TimelineStep(
                        label: 'En Route',
                        isComplete: _statusIndex(status) >= 3,
                        isActive: status == 'en_route',
                      ),
                      _TimelineStep(
                        label: 'Delivered',
                        isComplete: _statusIndex(status) >= 4,
                        isActive: status == 'delivered',
                        isLast: true,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: HelmTheme.error),
              const SizedBox(height: 16),
              Text('Failed to load delivery\n$error',
                  textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () =>
                    ref.invalidate(deliveryDetailProvider(deliveryId)),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  double _simulateX(String status) {
    switch (status) {
      case 'pending':
      case 'assigned':
        return 30;
      case 'pickup':
        return 80;
      case 'en_route':
        return 180;
      case 'delivered':
        return 260;
      default:
        return 30;
    }
  }

  double _simulateY(String status) {
    switch (status) {
      case 'pending':
      case 'assigned':
        return 40;
      case 'pickup':
        return 70;
      case 'en_route':
        return 120;
      case 'delivered':
        return 170;
      default:
        return 40;
    }
  }

  int _statusIndex(String status) {
    const statuses = ['pending', 'assigned', 'pickup', 'en_route', 'delivered'];
    return statuses.indexOf(status);
  }
}

class _MapPin extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String label;

  const _MapPin({
    required this.icon,
    required this.color,
    required this.label,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: color.withOpacity(0.3),
                blurRadius: 8,
                spreadRadius: 2,
              ),
            ],
          ),
          child: Icon(icon, color: Colors.white, size: 16),
        ),
        const SizedBox(height: 2),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            label,
            style: TextStyle(fontSize: 8, color: color),
          ),
        ),
      ],
    );
  }
}

class _StatusBanner extends StatelessWidget {
  final String status;

  const _StatusBanner({required this.status});

  Color get _color {
    switch (status) {
      case 'delivered':
        return HelmTheme.success;
      case 'en_route':
      case 'pickup':
        return HelmTheme.accent;
      case 'cancelled':
        return HelmTheme.error;
      default:
        return HelmTheme.primary;
    }
  }

  IconData get _icon {
    switch (status) {
      case 'delivered':
        return Icons.check_circle;
      case 'en_route':
        return Icons.directions_boat;
      case 'pickup':
        return Icons.inventory;
      case 'assigned':
        return Icons.person_pin;
      case 'cancelled':
        return Icons.cancel;
      default:
        return Icons.schedule;
    }
  }

  String get _label {
    switch (status) {
      case 'pending':
        return 'Pending';
      case 'assigned':
        return 'Assigned to Operator';
      case 'pickup':
        return 'Picking Up Order';
      case 'en_route':
        return 'En Route';
      case 'delivered':
        return 'Delivered';
      case 'cancelled':
        return 'Cancelled';
      default:
        return status;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _color.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          Icon(_icon, color: _color, size: 28),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _label,
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                  color: _color,
                ),
              ),
              Text(
                'Helm Dash Maritime Delivery',
                style: TextStyle(fontSize: 12, color: Colors.grey[600]),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _DetailRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(icon, size: 18, color: Colors.grey[600]),
          const SizedBox(width: 8),
          Text(label, style: TextStyle(color: Colors.grey[600])),
          const Spacer(),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}

class _TimelineStep extends StatelessWidget {
  final String label;
  final bool isComplete;
  final bool isActive;
  final bool isLast;

  const _TimelineStep({
    required this.label,
    required this.isComplete,
    this.isActive = false,
    this.isLast = false,
  });

  @override
  Widget build(BuildContext context) {
    final color = isComplete
        ? HelmTheme.success
        : isActive
            ? HelmTheme.accent
            : Colors.grey[300]!;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Column(
          children: [
            Container(
              width: 20,
              height: 20,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: isComplete ? color : Colors.white,
                border: Border.all(color: color, width: 2),
              ),
              child: isComplete
                  ? const Icon(Icons.check, size: 12, color: Colors.white)
                  : null,
            ),
            if (!isLast)
              Container(
                width: 2,
                height: 24,
                color: isComplete ? HelmTheme.success : Colors.grey[300],
              ),
          ],
        ),
        const SizedBox(width: 12),
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text(
            label,
            style: TextStyle(
              fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
              color: isActive ? HelmTheme.accent : null,
            ),
          ),
        ),
      ],
    );
  }
}
