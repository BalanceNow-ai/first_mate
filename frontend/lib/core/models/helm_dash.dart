import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

double _reqDouble(Map<String, dynamic> json, String key) {
  final value = optDouble(json, key);
  if (value == null) throw FormatException('Field "$key": expected number, got null');
  return value;
}


DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

/// Labels for Helm Dash delivery statuses (mirrors the server's labels; the
/// customer view uses the server's `status_label` directly).
String deliveryStatusLabel(String status) => switch (status) {
      'awaiting_dispatch' => 'Awaiting dispatch',
      'assigned' => 'Skipper assigned',
      'accepted' => 'Skipper accepted',
      'picked_up' => 'Picked up',
      'en_route' => 'En route',
      'delivered' => 'Delivered',
      'failed' => 'Failed',
      'cancelled' => 'Cancelled',
      _ => status,
    };

const terminalDeliveryStatuses = {'delivered', 'failed', 'cancelled'};
const trackingDeliveryStatuses = {'accepted', 'picked_up', 'en_route'};

/// A WGS84 point with an optional name.
class GeoPoint {
  const GeoPoint({required this.lat, required this.lng, this.name});

  final double lat;
  final double lng;
  final String? name;

  static GeoPoint? maybe(Map<String, dynamic>? json) {
    if (json == null) return null;
    return GeoPoint(
      lat: _reqDouble(json, 'lat'),
      lng: _reqDouble(json, 'lng'),
      name: opt<String>(json, 'name') ?? opt<String>(json, 'location_name'),
    );
  }
}

/// The latest position the server holds (`ReportedLocation`). It is shown as
/// reported — never interpolated or animated.
class ReportedLocation {
  const ReportedLocation({
    required this.lat,
    required this.lng,
    required this.recordedAt,
    required this.source,
    required this.isSimulated,
    required this.sourceLabel,
    required this.ageSeconds,
    this.accuracyM,
    this.headingDeg,
    this.speedKnots,
  });

  final double lat;
  final double lng;
  final double? accuracyM;
  final double? headingDeg;
  final double? speedKnots;
  final DateTime recordedAt;
  final String source;
  final bool isSimulated;
  final String sourceLabel;

  /// Age when the server answered.
  final int ageSeconds;

  factory ReportedLocation.fromJson(Map<String, dynamic> json) => ReportedLocation(
        lat: _reqDouble(json, 'lat'),
        lng: _reqDouble(json, 'lng'),
        accuracyM: optDouble(json, 'accuracy_m'),
        headingDeg: optDouble(json, 'heading_deg'),
        speedKnots: optDouble(json, 'speed_knots'),
        recordedAt: reqDate(json, 'recorded_at'),
        source: req<String>(json, 'source'),
        isSimulated: req<bool>(json, 'is_simulated'),
        sourceLabel: req<String>(json, 'source_label'),
        ageSeconds: req<int>(json, 'age_seconds'),
      );
}

/// "12 s ago", "4 min ago", "2 h ago".
String describeAge(Duration age) {
  final s = age.inSeconds < 0 ? 0 : age.inSeconds;
  if (s < 60) return '$s s ago';
  if (s < 3600) return '${s ~/ 60} min ago';
  return '${s ~/ 3600} h ${(s % 3600) ~/ 60} min ago';
}

class TimelineEntry {
  const TimelineEntry({required this.status, required this.label, required this.at});

  final String status;
  final String label;
  final DateTime at;

  factory TimelineEntry.fromJson(Map<String, dynamic> json) => TimelineEntry(
        status: req<String>(json, 'status'),
        label: req<String>(json, 'label'),
        at: reqDate(json, 'at'),
      );
}

/// Customer tracking for one Helm Dash delivery (`TrackingOut`).
class DeliveryTracking {
  const DeliveryTracking({
    required this.id,
    required this.orderId,
    required this.orderNumber,
    required this.status,
    required this.statusLabel,
    required this.deliveryPoint,
    required this.deliveryFeeCents,
    required this.currency,
    required this.timeline,
    required this.createdAt,
    required this.updatedAt,
    this.areaId,
    this.pickupLocation,
    this.deliveryLocationName,
    this.nauticalMiles,
    this.estimatedDeliveryMinutes,
    this.operatorDisplayName,
    this.operatorVesselName,
    this.latestLocation,
    this.locationMessage,
  });

  final String id;
  final String orderId;
  final String orderNumber;
  final String status;
  final String statusLabel;
  final String? areaId;
  final GeoPoint? pickupLocation;
  final GeoPoint deliveryPoint;
  final String? deliveryLocationName;
  final double? nauticalMiles;
  final int deliveryFeeCents;
  final String currency;
  final int? estimatedDeliveryMinutes;
  final String? operatorDisplayName;
  final String? operatorVesselName;
  final List<TimelineEntry> timeline;
  final ReportedLocation? latestLocation;
  final String? locationMessage;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isActive => !terminalDeliveryStatuses.contains(status);

  factory DeliveryTracking.fromJson(Map<String, dynamic> json) {
    final loc = optMap(json, 'latest_location');
    return DeliveryTracking(
      id: req<String>(json, 'id'),
      orderId: req<String>(json, 'order_id'),
      orderNumber: req<String>(json, 'order_number'),
      status: req<String>(json, 'status'),
      statusLabel: req<String>(json, 'status_label'),
      areaId: opt<String>(json, 'area_id'),
      pickupLocation: GeoPoint.maybe(optMap(json, 'pickup_location')),
      deliveryPoint: GeoPoint.maybe(reqMap(json, 'delivery_coordinates'))!,
      deliveryLocationName: opt<String>(json, 'delivery_location_name'),
      nauticalMiles: optDouble(json, 'nautical_miles'),
      deliveryFeeCents: centsFrom(json, 'delivery_fee_cents'),
      currency: opt<String>(json, 'currency') ?? 'NZD',
      estimatedDeliveryMinutes: opt<int>(json, 'estimated_delivery_minutes'),
      operatorDisplayName: opt<String>(json, 'operator_display_name'),
      operatorVesselName: opt<String>(json, 'operator_vessel_name'),
      timeline: [for (final t in mapList(json, 'timeline')) TimelineEntry.fromJson(t)],
      latestLocation: loc == null ? null : ReportedLocation.fromJson(loc),
      locationMessage: opt<String>(json, 'location_message'),
      createdAt: reqDate(json, 'created_at'),
      updatedAt: reqDate(json, 'updated_at'),
    );
  }
}

// ----------------------------------------------------------------- dispatch

/// An operating area with its admin fields (`AreaOut`).
class OperatingArea {
  const OperatingArea({
    required this.id,
    required this.name,
    required this.centerLat,
    required this.centerLng,
    required this.radiusNm,
    required this.enabled,
    required this.createdAt,
  });

  final String id;
  final String name;
  final double centerLat;
  final double centerLng;
  final double radiusNm;
  final bool enabled;
  final DateTime createdAt;

  factory OperatingArea.fromJson(Map<String, dynamic> json) => OperatingArea(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        centerLat: _reqDouble(json, 'center_lat'),
        centerLng: _reqDouble(json, 'center_lng'),
        radiusNm: _reqDouble(json, 'radius_nm'),
        enabled: req<bool>(json, 'enabled'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// A Helm Dash operator profile (`OperatorOut`).
class OperatorProfile {
  const OperatorProfile({
    required this.userId,
    required this.displayName,
    required this.areaId,
    required this.isOnline,
    required this.active,
    required this.certificationVerified,
    required this.createdAt,
    this.vesselName,
    this.certificationReference,
  });

  final String userId;
  final String displayName;
  final String? vesselName;
  final String areaId;
  final bool isOnline;
  final bool active;
  final String? certificationReference;

  /// Always false: the platform does not verify certifications.
  final bool certificationVerified;
  final DateTime createdAt;

  factory OperatorProfile.fromJson(Map<String, dynamic> json) => OperatorProfile(
        userId: req<String>(json, 'user_id'),
        displayName: req<String>(json, 'display_name'),
        vesselName: opt<String>(json, 'vessel_name'),
        areaId: req<String>(json, 'area_id'),
        isOnline: req<bool>(json, 'is_online'),
        active: req<bool>(json, 'active'),
        certificationReference: opt<String>(json, 'certification_reference'),
        certificationVerified: opt<bool>(json, 'certification_verified') ?? false,
        createdAt: reqDate(json, 'created_at'),
      );
}

/// A delivery status change (`StatusEventOut`).
class StatusEvent {
  const StatusEvent({
    required this.toStatus,
    required this.actorRole,
    required this.createdAt,
    this.fromStatus,
    this.actorId,
    this.note,
  });

  final String? fromStatus;
  final String toStatus;
  final String actorRole;
  final String? actorId;
  final String? note;
  final DateTime createdAt;

  factory StatusEvent.fromJson(Map<String, dynamic> json) => StatusEvent(
        fromStatus: opt<String>(json, 'from_status'),
        toStatus: req<String>(json, 'to_status'),
        actorRole: req<String>(json, 'actor_role'),
        actorId: opt<String>(json, 'actor_id'),
        note: opt<String>(json, 'note'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// Dispatcher / operator view of a delivery job (`DeliveryOut`, plus events
/// and the latest location for `DeliveryDetailOut`).
class DispatchDelivery {
  const DispatchDelivery({
    required this.id,
    required this.orderId,
    required this.status,
    required this.deliveryPoint,
    required this.deliveryFeeCents,
    required this.currency,
    required this.createdAt,
    required this.updatedAt,
    this.orderNumber,
    this.areaId,
    this.pickupLocation,
    this.deliveryLocationName,
    this.nauticalMiles,
    this.estimatedDeliveryMinutes,
    this.operatorId,
    this.operatorName,
    this.assignedAt,
    this.acceptedAt,
    this.pickedUpAt,
    this.deliveredAt,
    this.events,
    this.latestLocation,
  });

  final String id;
  final String orderId;
  final String? orderNumber;
  final String? areaId;
  final String status;
  final GeoPoint? pickupLocation;
  final GeoPoint deliveryPoint;
  final String? deliveryLocationName;
  final double? nauticalMiles;
  final int deliveryFeeCents;
  final String currency;
  final int? estimatedDeliveryMinutes;
  final String? operatorId;
  final String? operatorName;
  final DateTime? assignedAt;
  final DateTime? acceptedAt;
  final DateTime? pickedUpAt;
  final DateTime? deliveredAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Detail view only.
  final List<StatusEvent>? events;
  final ReportedLocation? latestLocation;

  bool get isTerminal => terminalDeliveryStatuses.contains(status);
  bool get acceptsPositions => trackingDeliveryStatuses.contains(status);

  factory DispatchDelivery.fromJson(Map<String, dynamic> json) {
    final events = json['events'];
    final loc = optMap(json, 'latest_location');
    return DispatchDelivery(
      id: req<String>(json, 'id'),
      orderId: req<String>(json, 'order_id'),
      orderNumber: opt<String>(json, 'order_number'),
      areaId: opt<String>(json, 'area_id'),
      status: req<String>(json, 'status'),
      pickupLocation: GeoPoint.maybe(optMap(json, 'pickup_location')),
      deliveryPoint: GeoPoint.maybe(reqMap(json, 'delivery_coordinates'))!,
      deliveryLocationName: opt<String>(json, 'delivery_location_name'),
      nauticalMiles: optDouble(json, 'nautical_miles'),
      deliveryFeeCents: centsFrom(json, 'delivery_fee_cents'),
      currency: opt<String>(json, 'currency') ?? 'NZD',
      estimatedDeliveryMinutes: opt<int>(json, 'estimated_delivery_minutes'),
      operatorId: opt<String>(json, 'operator_id'),
      operatorName: opt<String>(json, 'operator_name'),
      assignedAt: _optDate(json, 'assigned_at'),
      acceptedAt: _optDate(json, 'accepted_at'),
      pickedUpAt: _optDate(json, 'picked_up_at'),
      deliveredAt: _optDate(json, 'delivered_at'),
      createdAt: reqDate(json, 'created_at'),
      updatedAt: reqDate(json, 'updated_at'),
      events: events == null ? null : [for (final e in mapList(json, 'events')) StatusEvent.fromJson(e)],
      latestLocation: loc == null ? null : ReportedLocation.fromJson(loc),
    );
  }
}

/// `POST /dispatch/jobs/{id}/location` (201): the stored reading.
class LocationReceipt {
  const LocationReceipt({
    required this.id,
    required this.deliveryId,
    required this.lat,
    required this.lng,
    required this.recordedAt,
    required this.source,
  });

  final String id;
  final String deliveryId;
  final double lat;
  final double lng;
  final DateTime recordedAt;
  final String source;

  factory LocationReceipt.fromJson(Map<String, dynamic> json) => LocationReceipt(
        id: req<String>(json, 'id'),
        deliveryId: req<String>(json, 'delivery_id'),
        lat: _reqDouble(json, 'lat'),
        lng: _reqDouble(json, 'lng'),
        recordedAt: reqDate(json, 'recorded_at'),
        source: req<String>(json, 'source'),
      );
}

/// An operator payout record (`PayoutOut`). With no configured share the
/// status is `rate_unconfigured` and there is no amount (decision D10).
class Payout {
  const Payout({
    required this.id,
    required this.deliveryId,
    required this.operatorId,
    required this.grossFeeCents,
    required this.status,
    required this.createdAt,
    required this.currency,
    this.shareBps,
    this.amountCents,
    this.approvedBy,
    this.approvedAt,
    this.paidAt,
  });

  final String id;
  final String deliveryId;
  final String operatorId;
  final int grossFeeCents;
  final int? shareBps;
  final int? amountCents;
  final String status;
  final String? approvedBy;
  final DateTime? approvedAt;
  final DateTime? paidAt;
  final DateTime createdAt;
  final String currency;

  factory Payout.fromJson(Map<String, dynamic> json) => Payout(
        id: req<String>(json, 'id'),
        deliveryId: req<String>(json, 'delivery_id'),
        operatorId: req<String>(json, 'operator_id'),
        grossFeeCents: centsFrom(json, 'gross_fee_cents'),
        shareBps: opt<int>(json, 'share_bps'),
        amountCents: optionalCentsFrom(json, 'amount_cents'),
        status: req<String>(json, 'status'),
        approvedBy: opt<String>(json, 'approved_by'),
        approvedAt: _optDate(json, 'approved_at'),
        paidAt: _optDate(json, 'paid_at'),
        createdAt: reqDate(json, 'created_at'),
        currency: opt<String>(json, 'currency') ?? 'NZD',
      );
}

class PayoutStatusTotal {
  const PayoutStatusTotal({
    required this.status,
    required this.count,
    required this.amountCents,
    required this.grossFeeCents,
  });

  final String status;
  final int count;
  final int amountCents;
  final int grossFeeCents;

  factory PayoutStatusTotal.fromJson(Map<String, dynamic> json) => PayoutStatusTotal(
        status: req<String>(json, 'status'),
        count: req<int>(json, 'count'),
        amountCents: centsFrom(json, 'amount_cents'),
        grossFeeCents: centsFrom(json, 'gross_fee_cents'),
      );
}

/// `GET /dispatch/reconciliation`.
class Reconciliation {
  const Reconciliation({
    required this.period,
    required this.currency,
    required this.deliveredCount,
    required this.deliveryFeesCents,
    required this.payoutsByStatus,
    required this.livePayoutsEnabled,
    this.operatorShareBps,
  });

  final String period;
  final String currency;
  final int deliveredCount;
  final int deliveryFeesCents;
  final List<PayoutStatusTotal> payoutsByStatus;
  final int? operatorShareBps;
  final bool livePayoutsEnabled;

  factory Reconciliation.fromJson(Map<String, dynamic> json) => Reconciliation(
        period: req<String>(json, 'period'),
        currency: req<String>(json, 'currency'),
        deliveredCount: req<int>(json, 'delivered_count'),
        deliveryFeesCents: centsFrom(json, 'delivery_fees_cents'),
        payoutsByStatus: [
          for (final p in mapList(json, 'payouts_by_status')) PayoutStatusTotal.fromJson(p),
        ],
        operatorShareBps: opt<int>(json, 'operator_share_bps'),
        livePayoutsEnabled: req<bool>(json, 'live_payouts_enabled'),
      );
}
