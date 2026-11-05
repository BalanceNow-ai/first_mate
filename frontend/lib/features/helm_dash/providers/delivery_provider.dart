import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/features/orders/data/commerce_api.dart';

/// How often an active delivery is re-read.
final trackingPollIntervalProvider = Provider<Duration>((ref) => const Duration(seconds: 10));

/// Customer tracking for one delivery (`GET /helm-dash/deliveries/{id}`),
/// re-read every [trackingPollIntervalProvider] while the delivery is active.
/// Shows exactly what the server reports: the latest reported position (or
/// none), never an interpolated or invented one.
final deliveryTrackingProvider =
    AsyncNotifierProvider.autoDispose.family<DeliveryTrackingController, TrackingView, String>(
  DeliveryTrackingController.new,
);

/// The last server answer, when it was received, and the last refresh error.
class TrackingView {
  const TrackingView({required this.tracking, required this.receivedAt, this.pollError});

  final DeliveryTracking tracking;
  final DateTime receivedAt;
  final Object? pollError;
}

class DeliveryTrackingController extends AsyncNotifier<TrackingView> {
  DeliveryTrackingController(this.deliveryId);

  final String deliveryId;
  Timer? _timer;

  @override
  Future<TrackingView> build() async {
    final api = ref.watch(commerceApiProvider);
    ref.onDispose(() => _timer?.cancel());
    final tracking = await api.delivery(deliveryId);
    _schedule(tracking);
    return TrackingView(tracking: tracking, receivedAt: DateTime.now());
  }

  void _schedule(DeliveryTracking tracking) {
    _timer?.cancel();
    if (!tracking.isActive) return;
    _timer = Timer(ref.read(trackingPollIntervalProvider), _poll);
  }

  Future<void> _poll() async {
    if (!ref.mounted) return;
    try {
      final tracking = await ref.read(commerceApiProvider).delivery(deliveryId);
      if (!ref.mounted) return;
      state = AsyncData(TrackingView(tracking: tracking, receivedAt: DateTime.now()));
      _schedule(tracking);
    } catch (e) {
      if (!ref.mounted) return;
      // Keep the last good answer visible; surface the error and keep polling.
      final last = state.value;
      if (last == null) return;
      state = AsyncData(TrackingView(tracking: last.tracking, receivedAt: last.receivedAt, pollError: e));
      _schedule(last.tracking);
    }
  }

  Future<void> refresh() async {
    _timer?.cancel();
    await _poll();
  }
}
