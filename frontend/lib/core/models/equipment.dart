/// Vessel equipment, profile verification, service records and reminders
/// (`/vessels/{id}/equipment…`, `/service-records…`, `/service-reminders…`).
library;

import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

/// A calendar date (`YYYY-MM-DD`) as sent by the server.
DateTime? optDay(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

DateTime? optTimestamp(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

/// `YYYY-MM-DD` for a request body.
String dayString(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// `5 Nov 2026`.
String formatDay(DateTime d) => '${d.day} ${_months[d.month - 1]} ${d.year}';

/// How much an equipment record can be relied on (`EquipmentItem.reliability`).
enum Reliability {
  verified('verified', 'Verified'),
  ownerDeclared('owner_declared', 'Owner declared'),
  highConfidence('high_confidence', 'High confidence'),

  /// Low-confidence / unverified OEM data — never presented as fact.
  unconfirmed('unconfirmed', 'Unconfirmed');

  const Reliability(this.wire, this.label);

  final String wire;
  final String label;

  static Reliability parse(String value) =>
      Reliability.values.firstWhere((r) => r.wire == value, orElse: () => Reliability.unconfirmed);
}

/// Human label for an equipment provenance value.
String provenanceLabel(String provenance) => switch (provenance) {
      'owner_declared' => 'Added by you',
      'oem_database' => 'Factory record (boat database)',
      'staff_verified' => 'Verified by Helm staff',
      _ => provenance.replaceAll('_', ' '),
    };

/// Human label for a verification status.
String verificationLabel(String status) => switch (status) {
      'verified' => 'Verified',
      'pending_review' => 'Verification pending',
      'rejected' => 'Verification rejected',
      'unverified' => 'Not verified',
      _ => status.replaceAll('_', ' '),
    };

/// `EquipmentItem` — installed equipment (owner-added or applied OEM) or an
/// un-applied factory OEM record.
class EquipmentItem {
  const EquipmentItem({
    required this.id,
    required this.source,
    required this.vesselId,
    required this.category,
    required this.make,
    required this.origin,
    required this.provenance,
    required this.confidenceScore,
    required this.verificationStatus,
    required this.reliability,
    this.model,
    this.serialNumber,
    this.year,
    this.dataSource,
    this.isStandard,
    this.isSynthetic = false,
    this.oemEquipmentId,
    this.installedOn,
    this.removedAt,
    this.notes,
    this.displayNote,
    this.createdAt,
    this.updatedAt,
  });

  /// vessel_equipment id, or the OEM record id when [isFactory].
  final String id;

  /// `installed` | `factory_oem`.
  final String source;
  final String vesselId;
  final EquipmentCategory category;
  final String make;
  final String? model;
  final String? serialNumber;
  final int? year;

  /// `oem` | `user_added`.
  final String origin;

  /// `owner_declared` | `oem_database` | `staff_verified`.
  final String provenance;
  final String? dataSource;
  final double confidenceScore;
  final String verificationStatus;
  final Reliability reliability;
  final bool? isStandard;
  final bool isSynthetic;
  final String? oemEquipmentId;
  final DateTime? installedOn;
  final DateTime? removedAt;
  final String? notes;
  final String? displayNote;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isFactory => source == 'factory_oem';
  bool get isInstalled => source == 'installed';
  bool get isRemoved => removedAt != null;
  bool get isPendingReview => verificationStatus == 'pending_review';

  String get title => [make, model].whereType<String>().where((s) => s.isNotEmpty).join(' ');

  factory EquipmentItem.fromJson(Map<String, dynamic> json) => EquipmentItem(
        id: req<String>(json, 'id'),
        source: req<String>(json, 'source'),
        vesselId: req<String>(json, 'vessel_id'),
        category: EquipmentCategory.fromJson(reqMap(json, 'category')),
        make: req<String>(json, 'make'),
        model: opt<String>(json, 'model'),
        serialNumber: opt<String>(json, 'serial_number'),
        year: opt<int>(json, 'year'),
        origin: req<String>(json, 'origin'),
        provenance: req<String>(json, 'provenance'),
        dataSource: opt<String>(json, 'data_source'),
        confidenceScore: optDouble(json, 'confidence_score') ?? 0,
        verificationStatus: req<String>(json, 'verification_status'),
        reliability: Reliability.parse(req<String>(json, 'reliability')),
        isStandard: opt<bool>(json, 'is_standard'),
        isSynthetic: opt<bool>(json, 'is_synthetic') ?? false,
        oemEquipmentId: opt<String>(json, 'oem_equipment_id'),
        installedOn: optDay(json, 'installed_on'),
        removedAt: optTimestamp(json, 'removed_at'),
        notes: opt<String>(json, 'notes'),
        displayNote: opt<String>(json, 'display_note'),
        createdAt: optTimestamp(json, 'created_at'),
        updatedAt: optTimestamp(json, 'updated_at'),
      );
}

/// `EquipmentListResponse`.
class EquipmentList {
  const EquipmentList({required this.vesselId, required this.items, this.modelYearId});

  final String vesselId;
  final String? modelYearId;
  final List<EquipmentItem> items;

  List<EquipmentItem> get installed => [for (final i in items) if (i.isInstalled && !i.isRemoved) i];
  List<EquipmentItem> get removed => [for (final i in items) if (i.isInstalled && i.isRemoved) i];
  List<EquipmentItem> get factory => [for (final i in items) if (i.isFactory) i];

  factory EquipmentList.fromJson(Map<String, dynamic> json) => EquipmentList(
        vesselId: req<String>(json, 'vessel_id'),
        modelYearId: opt<String>(json, 'model_year_id'),
        items: [for (final i in mapList(json, 'items')) EquipmentItem.fromJson(i)],
      );
}

/// Form values for `EquipmentCreate` / `EquipmentUpdate`.
class EquipmentDraft {
  const EquipmentDraft({
    required this.category,
    required this.make,
    this.model,
    this.serialNumber,
    this.year,
    this.installedOn,
    this.notes,
  });

  /// Equipment category slug.
  final String category;
  final String make;
  final String? model;
  final String? serialNumber;
  final int? year;
  final DateTime? installedOn;
  final String? notes;

  Map<String, dynamic> _fields() => {
        'category': category,
        'make': make,
        'model': model,
        'serial_number': serialNumber,
        'year': year,
        'installed_on': installedOn == null ? null : dayString(installedOn!),
        'notes': notes,
      };

  /// POST body (empty optional fields omitted).
  Map<String, dynamic> toCreateJson() => _fields()..removeWhere((_, v) => v == null);

  /// PATCH body (optional fields sent as null to clear them).
  Map<String, dynamic> toUpdateJson() => _fields();
}

/// `ApplyOEMResponse`.
class ApplyOemResult {
  const ApplyOemResult({required this.created, required this.skippedAlreadyApplied});

  final List<EquipmentItem> created;
  final List<String> skippedAlreadyApplied;

  factory ApplyOemResult.fromJson(Map<String, dynamic> json) => ApplyOemResult(
        created: [for (final i in mapList(json, 'created')) EquipmentItem.fromJson(i)],
        skippedAlreadyApplied: stringList(json, 'skipped_already_applied'),
      );
}

/// `VerificationRequestResponse`.
class VerificationRequest {
  const VerificationRequest({
    required this.id,
    required this.vesselId,
    required this.status,
    required this.createdAt,
    this.submittedNote,
    this.evidenceUrl,
    this.reviewedAt,
    this.reviewNote,
    this.equipmentIds = const [],
  });

  final String id;
  final String vesselId;

  /// `pending` | `approved` | `rejected`.
  final String status;
  final String? submittedNote;
  final String? evidenceUrl;
  final DateTime? reviewedAt;
  final String? reviewNote;
  final DateTime createdAt;
  final List<String> equipmentIds;

  bool get isPending => status == 'pending';

  factory VerificationRequest.fromJson(Map<String, dynamic> json) => VerificationRequest(
        id: req<String>(json, 'id'),
        vesselId: req<String>(json, 'vessel_id'),
        status: req<String>(json, 'status'),
        submittedNote: opt<String>(json, 'submitted_note'),
        evidenceUrl: opt<String>(json, 'evidence_url'),
        reviewedAt: optTimestamp(json, 'reviewed_at'),
        reviewNote: opt<String>(json, 'review_note'),
        createdAt: reqDate(json, 'created_at'),
        equipmentIds: stringList(json, 'equipment_ids'),
      );
}

/// `ServiceRecordResponse`.
class ServiceRecord {
  const ServiceRecord({
    required this.id,
    required this.vesselId,
    required this.serviceType,
    required this.performedOn,
    required this.createdAt,
    this.equipmentId,
    this.engineHours,
    this.providerName,
    this.costCents,
    this.currency = 'NZD',
    this.notes,
  });

  final String id;
  final String vesselId;
  final String? equipmentId;
  final String serviceType;
  final DateTime performedOn;
  final int? engineHours;
  final String? providerName;
  final int? costCents;
  final String currency;
  final String? notes;
  final DateTime createdAt;

  String? get costText => costCents == null ? null : formatCents(costCents!, currency: currency);

  factory ServiceRecord.fromJson(Map<String, dynamic> json) => ServiceRecord(
        id: req<String>(json, 'id'),
        vesselId: req<String>(json, 'vessel_id'),
        equipmentId: opt<String>(json, 'equipment_id'),
        serviceType: req<String>(json, 'service_type'),
        performedOn: DateTime.parse(req<String>(json, 'performed_on')),
        engineHours: opt<int>(json, 'engine_hours'),
        providerName: opt<String>(json, 'provider_name'),
        costCents: optionalCentsFrom(json, 'cost_cents'),
        currency: opt<String>(json, 'currency') ?? 'NZD',
        notes: opt<String>(json, 'notes'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// Form values for `ServiceRecordCreate` / `ServiceRecordUpdate`.
class ServiceRecordDraft {
  const ServiceRecordDraft({
    required this.serviceType,
    required this.performedOn,
    this.engineHours,
    this.providerName,
    this.costCents,
    this.notes,
    this.equipmentId,
  });

  final String serviceType;
  final DateTime performedOn;
  final int? engineHours;
  final String? providerName;
  final int? costCents;
  final String? notes;
  final String? equipmentId;

  Map<String, dynamic> _fields() => {
        'service_type': serviceType,
        'performed_on': dayString(performedOn),
        'engine_hours': engineHours,
        'provider_name': providerName,
        'cost_cents': costCents,
        'notes': notes,
        'equipment_id': equipmentId,
      };

  Map<String, dynamic> toCreateJson() => _fields()..removeWhere((_, v) => v == null);
  Map<String, dynamic> toUpdateJson() => _fields();
}

/// `ReminderResponse`.
class ServiceReminder {
  const ServiceReminder({
    required this.id,
    required this.vesselId,
    required this.title,
    required this.status,
    required this.source,
    required this.isDue,
    required this.createdAt,
    required this.updatedAt,
    this.equipmentId,
    this.dueOn,
    this.dueEngineHours,
    this.intervalMonths,
    this.intervalHours,
  });

  final String id;
  final String vesselId;
  final String? equipmentId;
  final String title;
  final DateTime? dueOn;
  final int? dueEngineHours;
  final int? intervalMonths;
  final int? intervalHours;

  /// `active` | `completed` | `dismissed`.
  final String status;
  final String source;
  final bool isDue;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isActive => status == 'active';

  /// `Due 1 Oct 2026 or at 200 h`.
  String get dueText {
    final parts = [
      if (dueOn != null) formatDay(dueOn!),
      if (dueEngineHours != null) 'at $dueEngineHours engine hours',
    ];
    return parts.isEmpty ? 'No due point' : 'Due ${parts.join(' or ')}';
  }

  String? get intervalText {
    final parts = [
      if (intervalMonths != null) 'every $intervalMonths months',
      if (intervalHours != null) 'every $intervalHours hours',
    ];
    return parts.isEmpty ? null : 'Repeats ${parts.join(' or ')}';
  }

  factory ServiceReminder.fromJson(Map<String, dynamic> json) => ServiceReminder(
        id: req<String>(json, 'id'),
        vesselId: req<String>(json, 'vessel_id'),
        equipmentId: opt<String>(json, 'equipment_id'),
        title: req<String>(json, 'title'),
        dueOn: optDay(json, 'due_on'),
        dueEngineHours: opt<int>(json, 'due_engine_hours'),
        intervalMonths: opt<int>(json, 'interval_months'),
        intervalHours: opt<int>(json, 'interval_hours'),
        status: req<String>(json, 'status'),
        source: req<String>(json, 'source'),
        isDue: opt<bool>(json, 'is_due') ?? false,
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

/// Form values for `ReminderCreate` / `ReminderUpdate`.
class ReminderDraft {
  const ReminderDraft({
    required this.title,
    this.dueOn,
    this.dueEngineHours,
    this.intervalMonths,
    this.intervalHours,
    this.equipmentId,
  });

  final String title;
  final DateTime? dueOn;
  final int? dueEngineHours;
  final int? intervalMonths;
  final int? intervalHours;
  final String? equipmentId;

  Map<String, dynamic> _fields() => {
        'title': title,
        'due_on': dueOn == null ? null : dayString(dueOn!),
        'due_engine_hours': dueEngineHours,
        'interval_months': intervalMonths,
        'interval_hours': intervalHours,
        'equipment_id': equipmentId,
      };

  Map<String, dynamic> toCreateJson() => _fields()..removeWhere((_, v) => v == null);
  Map<String, dynamic> toUpdateJson() => _fields();
}

/// `ReminderCompleteResponse`.
class ReminderCompletion {
  const ReminderCompletion({required this.completed, this.next, this.serviceRecord});

  final ServiceReminder completed;
  final ServiceReminder? next;
  final ServiceRecord? serviceRecord;

  factory ReminderCompletion.fromJson(Map<String, dynamic> json) {
    final next = optMap(json, 'next');
    final record = optMap(json, 'service_record');
    return ReminderCompletion(
      completed: ServiceReminder.fromJson(reqMap(json, 'completed')),
      next: next == null ? null : ServiceReminder.fromJson(next),
      serviceRecord: record == null ? null : ServiceRecord.fromJson(record),
    );
  }
}
