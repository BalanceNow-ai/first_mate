import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/helm_dash.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/dispatch/data/dispatch_api.dart';
import 'package:helm_marine/features/dispatch/data/geolocation.dart';
import 'package:helm_marine/features/dispatch/widgets/dispatch_widgets.dart';
import 'package:helm_marine/features/orders/widgets/order_widgets.dart';
import 'package:helm_marine/features/staff_orders/screens/staff_common.dart';

final operatorProfileProvider = FutureProvider.autoDispose<OperatorProfile>((ref) {
  return ref.watch(staffApiProvider).myOperatorProfile();
});

final operatorJobsProvider = FutureProvider.autoDispose.family<List<DispatchDelivery>, bool>((ref, includeFinished) {
  return ref.watch(staffApiProvider).myJobs(includeFinished: includeFinished);
});

final operatorJobProvider = FutureProvider.autoDispose.family<DispatchDelivery, String>((ref, id) {
  return ref.watch(staffApiProvider).myJob(id);
});

/// Reads the device position for [OperatorJobScreen]; overridable in tests.
final devicePositionReaderProvider = Provider<Future<DeviceReading> Function()>((ref) => readDevicePosition);

/// Whether this build can read the device position; overridable in tests.
final geolocationAvailableProvider = Provider<bool>((ref) => geolocationSupported);

/// `/staff/operator` — availability and my jobs.
/// Readings less precise than this are not shared as a vessel position.
const double maxShareableAccuracyM = 1000;

class OperatorHomeScreen extends ConsumerStatefulWidget {
  const OperatorHomeScreen({super.key});

  @override
  ConsumerState<OperatorHomeScreen> createState() => _OperatorHomeScreenState();
}

class _OperatorHomeScreenState extends ConsumerState<OperatorHomeScreen> {
  bool _finished = false;
  bool _busy = false;

  Future<void> _setOnline(bool online) async {
    setState(() => _busy = true);
    final result = await runStaffAction(
      context,
      () => ref.read(staffApiProvider).setAvailability(online),
      success: online ? 'You are online for Helm Dash jobs' : 'You are offline',
    );
    if (mounted) setState(() => _busy = false);
    if (result != null) ref.invalidate(operatorProfileProvider);
  }

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'operator'},
      title: 'Operator jobs',
      builder: (context, me) {
        final profile = ref.watch(operatorProfileProvider);
        final jobs = ref.watch(operatorJobsProvider(_finished));
        return Scaffold(
          appBar: AppBar(
            title: const Text('Operator jobs'),
            actions: [
              IconButton(
                tooltip: 'Refresh',
                icon: const Icon(Icons.refresh),
                onPressed: () {
                  ref.invalidate(operatorProfileProvider);
                  ref.invalidate(operatorJobsProvider(_finished));
                },
              ),
            ],
          ),
          body: ContentWidth(
            maxWidth: 900,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                profile.when(
                  loading: () => const LinearProgressIndicator(),
                  error: (e, _) {
                    final api = ApiError.from(e);
                    if (api?.code == 'not_an_operator') {
                      return const Card(
                        child: ListTile(
                          leading: Icon(Icons.info_outline),
                          title: Text('No operator profile'),
                          subtitle: Text('An admin must create and activate a Helm Dash operator profile for this account.'),
                        ),
                      );
                    }
                    return ErrorView(error: e, onRetry: () => ref.invalidate(operatorProfileProvider));
                  },
                  data: (p) => Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(p.displayName, style: Theme.of(context).textTheme.titleMedium),
                        Text('${p.vesselName ?? 'No vessel name'} · area ${p.areaId}'),
                        Text(p.active ? 'Profile active' : 'Profile not active — an admin must activate it',
                            style: TextStyle(color: p.active ? HelmTheme.success : HelmTheme.warning)),
                        if (p.certificationReference != null)
                          Text('Certification reference (unverified): ${p.certificationReference}'),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Available for jobs'),
                          subtitle: Text(p.isOnline ? 'Online' : 'Offline'),
                          value: p.isOnline,
                          onChanged: _busy ? null : _setOnline,
                        ),
                      ]),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(child: Text('My jobs', style: Theme.of(context).textTheme.titleMedium)),
                  FilterChip(
                    label: const Text('Include finished'),
                    selected: _finished,
                    onSelected: (v) => setState(() => _finished = v),
                  ),
                ]),
                ...jobs.when(
                  loading: () => [const LoadingView(message: 'Loading jobs…')],
                  error: (e, _) => [
                    if (ApiError.from(e)?.code == 'not_an_operator')
                      const SizedBox.shrink()
                    else
                      ErrorView(error: e, onRetry: () => ref.invalidate(operatorJobsProvider(_finished))),
                  ],
                  data: (list) => [
                    if (list.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No jobs assigned to you.')),
                    for (final j in list) DeliveryTile(delivery: j, onTap: () => context.go('/staff/operator/jobs/${j.id}')),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// `/staff/operator/jobs/:id` — accept / decline, status steps, share position.
class OperatorJobScreen extends ConsumerStatefulWidget {
  const OperatorJobScreen({super.key, required this.deliveryId});

  final String deliveryId;

  @override
  ConsumerState<OperatorJobScreen> createState() => _OperatorJobScreenState();
}

class _OperatorJobScreenState extends ConsumerState<OperatorJobScreen> {
  bool _busy = false;
  String? _shareStatus;
  bool _shareError = false;

  void _reload() {
    ref.invalidate(operatorJobProvider(widget.deliveryId));
    ref.invalidate(operatorJobsProvider);
  }

  Future<void> _run(Future<Object?> Function() action, String success) async {
    setState(() => _busy = true);
    final r = await runStaffAction(context, action, success: success);
    if (mounted) setState(() => _busy = false);
    if (r != null) _reload();
  }

  Future<void> _shareLocation() async {
    final ok = await confirmAction(
      context,
      title: 'Share your current position?',
      message: 'Helm will ask this device for its current location (your browser may ask for permission) and send '
          'that one reading to the customer\'s tracking page. Nothing is shared until you continue.',
      action: 'Share position',
    );
    if (!ok || !mounted) return;
    setState(() {
      _busy = true;
      _shareStatus = 'Reading your position…';
      _shareError = false;
    });
    try {
      final reading = await ref.read(devicePositionReaderProvider)();
      final accuracy = reading.accuracyM;
      if (accuracy != null && accuracy > maxShareableAccuracyM) {
        // A coarse (e.g. network/IP-based) fix is not a usable vessel position.
        if (!mounted) return;
        setState(() {
          _shareError = true;
          _shareStatus = 'Your device only reported a rough position '
              '(±${(accuracy / 1000).toStringAsFixed(1)} km), so it was not shared. '
              'Turn on precise location / GPS and try again.';
        });
        return;
      }
      final receipt = await ref.read(staffApiProvider).reportLocation(
            widget.deliveryId,
            lat: reading.lat,
            lng: reading.lng,
            recordedAt: reading.recordedAt,
            accuracyM: reading.accuracyM,
            headingDeg: reading.headingDeg,
            speedKnots: reading.speedKnots,
          );
      if (!mounted) return;
      setState(() {
        _shareStatus = 'Position shared: ${receipt.lat.toStringAsFixed(5)}, ${receipt.lng.toStringAsFixed(5)} '
            '(recorded ${formatLocalDateTime(receipt.recordedAt)}'
            '${reading.accuracyM != null ? ', ±${reading.accuracyM!.round()} m' : ''}).';
      });
      _reload();
    } catch (e) {
      if (!mounted) return;
      final api = ApiError.from(e);
      setState(() {
        _shareError = true;
        _shareStatus = api != null ? '${staffErrorText(api)} (${api.code})' : describeError(e);
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return RoleGate(
      roles: const {'operator'},
      title: 'Job',
      builder: (context, me) {
        final async = ref.watch(operatorJobProvider(widget.deliveryId));
        final api = ref.read(staffApiProvider);
        return Scaffold(
          appBar: AppBar(
            title: Text(async.value?.orderNumber == null ? 'Job' : 'Job · ${async.value!.orderNumber}'),
            actions: [IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: _reload)],
          ),
          body: async.when(
            loading: () => const LoadingView(),
            error: (e, _) => ErrorView(error: e, onRetry: _reload),
            data: (j) {
              final next = switch (j.status) {
                'accepted' => ('picked_up', 'Picked up'),
                'picked_up' => ('en_route', 'En route'),
                'en_route' => ('delivered', 'Delivered'),
                _ => null,
              };
              return ContentWidth(
                maxWidth: 900,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    DeliveryStatusChip(status: j.status),
                    const SizedBox(height: 12),
                    DeliveryMap(delivery: j),
                    StaffSection(
                      title: 'Deliver to',
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(j.deliveryLocationName ?? 'Pinned position'),
                        Text('${j.deliveryPoint.lat.toStringAsFixed(5)}, ${j.deliveryPoint.lng.toStringAsFixed(5)}'),
                        if (j.pickupLocation != null) Text('Pick up from ${j.pickupLocation!.name ?? 'the warehouse'}'),
                        Text('${j.nauticalMiles?.toStringAsFixed(2) ?? '?'} nm · fee ${formatCents(j.deliveryFeeCents)}'),
                      ]),
                    ),
                    StaffSection(
                      title: 'Actions',
                      child: Wrap(spacing: 8, runSpacing: 8, children: [
                        if (j.status == 'assigned') ...[
                          FilledButton(
                            onPressed: _busy ? null : () => _run(() => api.acceptJob(j.id), 'Job accepted'),
                            child: const Text('Accept job'),
                          ),
                          OutlinedButton(
                            onPressed: _busy
                                ? null
                                : () async {
                                    final reason = await askReason(context, title: 'Decline this job?', action: 'Decline');
                                    if (reason != null) await _run(() => api.declineJob(j.id, reason: reason), 'Job declined');
                                  },
                            child: const Text('Decline'),
                          ),
                        ],
                        if (next != null)
                          FilledButton(
                            onPressed: _busy ? null : () => _run(() => api.setJobStatus(j.id, next.$1), 'Status: ${next.$2}'),
                            child: Text('Mark ${next.$2.toLowerCase()}'),
                          ),
                        if (j.acceptsPositions)
                          OutlinedButton(
                            onPressed: _busy
                                ? null
                                : () async {
                                    final note = await askReason(context, title: 'Mark this delivery failed?', action: 'Mark failed');
                                    if (note != null) await _run(() => api.setJobStatus(j.id, 'failed', note: note), 'Delivery marked failed');
                                  },
                            child: const Text('Mark failed'),
                          ),
                        if (j.isTerminal) Text('This job is ${deliveryStatusLabel(j.status).toLowerCase()}.'),
                      ]),
                    ),
                    if (j.acceptsPositions)
                      StaffSection(
                        title: 'Share position',
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          const Text('Send one reading from this device\'s location service to the customer\'s tracking. '
                              'Positions are only sent when you press the button.'),
                          const SizedBox(height: 8),
                          if (!ref.watch(geolocationAvailableProvider))
                            const Text('Location sharing is available in the web dispatch app in this build.')
                          else
                            FilledButton.icon(
                              onPressed: _busy ? null : _shareLocation,
                              icon: const Icon(Icons.my_location),
                              label: const Text('Share my current position'),
                            ),
                          if (_shareStatus != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Semantics(
                                liveRegion: true,
                                child: Text(_shareStatus!,
                                    style: TextStyle(color: _shareError ? HelmTheme.error : HelmTheme.success)),
                              ),
                            ),
                        ]),
                      ),
                    StaffSection(title: 'Last reported position', child: LatestLocationText(location: j.latestLocation)),
                    StaffSection(title: 'Events', child: DeliveryEvents(events: j.events ?? const [])),
                  ],
                ),
              );
            },
          ),
        );
      },
    );
  }
}
