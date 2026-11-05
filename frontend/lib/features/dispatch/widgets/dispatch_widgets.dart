import 'package:flutter/material.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/helm_dash/widgets/sea_map.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:latlong2/latlong.dart';

Color deliveryStatusColor(String status) => switch (status) {
      'awaiting_dispatch' => HelmTheme.warning,
      'delivered' => HelmTheme.success,
      'failed' || 'cancelled' => HelmTheme.error,
      _ => HelmTheme.ocean,
    };

class DeliveryStatusChip extends StatelessWidget {
  const DeliveryStatusChip({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) => LabelChip(
        label: deliveryStatusLabel(status),
        color: deliveryStatusColor(status),
        semanticPrefix: 'Delivery status',
      );
}

/// A row in the dispatcher / operator job lists.
class DeliveryTile extends StatelessWidget {
  const DeliveryTile({super.key, required this.delivery, required this.onTap});

  final DispatchDelivery delivery;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final d = delivery;
    return Card(
      child: ListTile(
        onTap: onTap,
        leading: const Icon(Icons.sailing),
        title: Text('Order ${d.orderNumber ?? d.orderId}'),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text([
            d.deliveryLocationName ?? '${d.deliveryPoint.lat.toStringAsFixed(4)}, ${d.deliveryPoint.lng.toStringAsFixed(4)}',
            if (d.areaId != null) d.areaId!,
            if (d.nauticalMiles != null) '${d.nauticalMiles!.toStringAsFixed(1)} nm',
          ].join(' · ')),
          Text(d.operatorName == null ? 'Unassigned' : 'Skipper ${d.operatorName}'),
          const SizedBox(height: 4),
          DeliveryStatusChip(status: d.status),
        ]),
        trailing: Text(formatCents(d.deliveryFeeCents)),
      ),
    );
  }
}

/// Destination, pickup and the latest reported position of a job.
class DeliveryMap extends StatelessWidget {
  const DeliveryMap({super.key, required this.delivery, this.height = 280});

  final DispatchDelivery delivery;
  final double height;

  @override
  Widget build(BuildContext context) {
    final d = delivery;
    final loc = d.latestLocation;
    final dest = LatLng(d.deliveryPoint.lat, d.deliveryPoint.lng);
    return SizedBox(
      height: height,
      child: SeaMap(
        center: loc == null ? dest : LatLng(loc.lat, loc.lng),
        zoom: 11,
        markers: [
          SeaMarker(point: dest, label: d.deliveryLocationName ?? 'Delivery point', icon: Icons.location_pin, color: HelmTheme.coral),
          if (d.pickupLocation != null)
            SeaMarker(
              point: LatLng(d.pickupLocation!.lat, d.pickupLocation!.lng),
              label: d.pickupLocation!.name ?? 'Pickup',
              icon: Icons.warehouse,
              color: HelmTheme.navy,
            ),
          if (loc != null)
            SeaMarker(
              point: LatLng(loc.lat, loc.lng),
              label: loc.isSimulated ? 'Latest position (simulated, local test)' : 'Latest reported position',
              icon: Icons.directions_boat,
              color: loc.isSimulated ? HelmTheme.warning : HelmTheme.ocean,
            ),
        ],
      ),
    );
  }
}

/// Text summary of the latest reported location.
class LatestLocationText extends StatelessWidget {
  const LatestLocationText({super.key, required this.location});

  final ReportedLocation? location;

  @override
  Widget build(BuildContext context) {
    final l = location;
    if (l == null) return const Text('No position reported yet.');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (l.isSimulated) const LabelChip(label: 'Simulated (local test)', color: HelmTheme.warning, icon: Icons.science),
      Text('${l.lat.toStringAsFixed(5)}, ${l.lng.toStringAsFixed(5)}'
          '${l.accuracyM != null ? ' (±${l.accuracyM!.round()} m)' : ''}'),
      Text('${l.sourceLabel} · reported ${describeAge(Duration(seconds: l.ageSeconds))} '
          '(${formatLocalDateTime(l.recordedAt)})'),
    ]);
  }
}

/// Status change history.
class DeliveryEvents extends StatelessWidget {
  const DeliveryEvents({super.key, required this.events});

  final List<StatusEvent> events;

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) return const Text('No events.');
    return Column(children: [
      for (final e in events)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.history),
          title: Text('${e.fromStatus == null ? '' : '${deliveryStatusLabel(e.fromStatus!)} → '}${deliveryStatusLabel(e.toStatus)}'),
          subtitle: Text('${e.actorRole} · ${formatLocalDateTime(e.createdAt)}${e.note == null ? '' : ' · ${e.note}'}'),
        ),
    ]);
  }
}
