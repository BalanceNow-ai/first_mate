import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/helm_dash/providers/delivery_provider.dart';
import 'package:helm_marine/features/helm_dash/widgets/sea_map.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:latlong2/latlong.dart';

/// Customer Helm Dash tracking: status timeline, skipper, and the latest
/// *reported* position only (no interpolation, no animation between reports).
class DeliveryTrackingScreen extends ConsumerWidget {
  const DeliveryTrackingScreen({super.key, required this.deliveryId});

  final String deliveryId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(deliveryTrackingProvider(deliveryId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Helm Dash tracking'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.read(deliveryTrackingProvider(deliveryId).notifier).refresh(),
          ),
        ],
      ),
      body: async.when(
        loading: () => const LoadingView(message: 'Loading delivery…'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load this delivery',
          onRetry: () => ref.invalidate(deliveryTrackingProvider(deliveryId)),
        ),
        data: (view) => _TrackingBody(view: view),
      ),
    );
  }
}

class _TrackingBody extends StatelessWidget {
  const _TrackingBody({required this.view});

  final TrackingView view;

  @override
  Widget build(BuildContext context) {
    final t = view.tracking;
    final theme = Theme.of(context);
    final loc = t.latestLocation;
    final destination = LatLng(t.deliveryPoint.lat, t.deliveryPoint.lng);
    final markers = <SeaMarker>[
      SeaMarker(
        point: destination,
        label: 'Delivery point${t.deliveryLocationName == null ? '' : ': ${t.deliveryLocationName}'}',
        icon: Icons.location_pin,
        color: HelmTheme.coral,
      ),
      if (t.pickupLocation != null)
        SeaMarker(
          point: LatLng(t.pickupLocation!.lat, t.pickupLocation!.lng),
          label: t.pickupLocation!.name ?? 'Pickup',
          icon: Icons.warehouse,
          color: HelmTheme.navy,
        ),
      if (loc != null)
        SeaMarker(
          point: LatLng(loc.lat, loc.lng),
          label: loc.isSimulated ? 'Last reported position (simulated, local test)' : 'Last reported position',
          icon: Icons.directions_boat,
          color: loc.isSimulated ? HelmTheme.warning : HelmTheme.ocean,
        ),
    ];
    return ContentWidth(
      maxWidth: 960,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Semantics(
            header: true,
            child: Text('Order ${t.orderNumber}', style: theme.textTheme.titleLarge),
          ),
          const SizedBox(height: 8),
          Semantics(
            liveRegion: true,
            child: LabelChip(
              label: t.statusLabel,
              color: t.status == 'delivered'
                  ? HelmTheme.success
                  : (t.status == 'failed' || t.status == 'cancelled')
                      ? HelmTheme.error
                      : HelmTheme.ocean,
              icon: Icons.sailing,
              semanticPrefix: 'Delivery status',
            ),
          ),
          const SizedBox(height: 8),
          if (t.operatorDisplayName != null)
            Text('Skipper: ${t.operatorDisplayName}${t.operatorVesselName == null ? '' : ' · ${t.operatorVesselName}'}')
          else
            const Text('No skipper assigned yet.'),
          const SizedBox(height: 12),
          SizedBox(
            height: 320,
            child: SeaMap(
              center: loc != null ? LatLng(loc.lat, loc.lng) : destination,
              zoom: 11,
              markers: markers,
            ),
          ),
          const SizedBox(height: 12),
          _PositionPanel(view: view),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(header: true, child: Text('Delivery', style: theme.textTheme.titleMedium)),
                  const SizedBox(height: 6),
                  if (t.deliveryLocationName != null) Text(t.deliveryLocationName!),
                  Text('${t.deliveryPoint.lat.toStringAsFixed(5)}, ${t.deliveryPoint.lng.toStringAsFixed(5)}'),
                  if (t.nauticalMiles != null) Text('${t.nauticalMiles!.toStringAsFixed(2)} nm from the warehouse'),
                  if (t.estimatedDeliveryMinutes != null)
                    Text('Estimated ${t.estimatedDeliveryMinutes} min once the skipper departs'),
                  Text('Helm Dash fee ${formatCents(t.deliveryFeeCents)}'),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(header: true, child: Text('Timeline', style: theme.textTheme.titleMedium)),
                  const SizedBox(height: 6),
                  for (final e in t.timeline)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      leading: Icon(
                        e.status == t.status ? Icons.radio_button_checked : Icons.check_circle_outline,
                        color: e.status == t.status ? HelmTheme.primary : HelmTheme.success,
                      ),
                      title: Text(e.label),
                      subtitle: Text(formatLocalDateTime(e.at)),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => context.go('/orders/${t.orderId}'),
            icon: const Icon(Icons.receipt_long),
            label: const Text('View order'),
          ),
        ],
      ),
    );
  }
}

/// The latest reported position, its source and age — or why there is none.
class _PositionPanel extends StatefulWidget {
  const _PositionPanel({required this.view});

  final TrackingView view;

  @override
  State<_PositionPanel> createState() => _PositionPanelState();
}

class _PositionPanelState extends State<_PositionPanel> {
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.view.tracking;
    final loc = t.latestLocation;
    final theme = Theme.of(context);
    final children = <Widget>[];
    if (loc == null) {
      children.add(Row(children: [
        const Icon(Icons.gps_not_fixed, color: HelmTheme.mutedText),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            t.locationMessage ?? (t.isActive ? 'Awaiting first position report' : 'No position was reported.'),
            style: theme.textTheme.titleSmall,
          ),
        ),
      ]));
    } else {
      // Server age at the time of the answer plus the time since then.
      final age = Duration(seconds: loc.ageSeconds) + DateTime.now().difference(widget.view.receivedAt);
      children.addAll([
        Row(children: [
          Icon(Icons.gps_fixed, color: loc.isSimulated ? HelmTheme.warning : HelmTheme.ocean),
          const SizedBox(width: 8),
          Expanded(child: Text('Last reported ${describeAge(age)}', style: theme.textTheme.titleSmall)),
        ]),
        const SizedBox(height: 4),
        if (loc.isSimulated)
          const LabelChip(label: 'Simulated (local test)', color: HelmTheme.warning, icon: Icons.science),
        Text(loc.sourceLabel),
        Text('Position ${loc.lat.toStringAsFixed(5)}, ${loc.lng.toStringAsFixed(5)}'
            '${loc.accuracyM != null ? ' (±${loc.accuracyM!.round()} m)' : ''}'),
        Text('Recorded ${formatLocalDateTime(loc.recordedAt)}', style: theme.textTheme.bodySmall),
        Text('Shown as reported — positions are not estimated between reports.', style: theme.textTheme.bodySmall),
      ]);
    }
    if (t.isActive) {
      children.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text('Updates automatically every 10 seconds.', style: theme.textTheme.bodySmall),
      ));
    }
    if (widget.view.pollError != null) {
      children.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text('Could not refresh: ${describeError(widget.view.pollError!)}',
            style: const TextStyle(color: HelmTheme.error)),
      ));
    }
    return Semantics(
      container: true,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
        ),
      ),
    );
  }
}
