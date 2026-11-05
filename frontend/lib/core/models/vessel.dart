import 'package:helm_marine/core/models/json.dart';

/// Hull types accepted by the server (`HULL_TYPES`).
const hullTypes = ['aluminium', 'fibreglass', 'inflatable', 'timber', 'steel', 'other'];

/// Propulsion types accepted by the server (`PROPULSION_TYPES`).
const propulsionTypes = [
  'outboard', 'inboard', 'sterndrive', 'jet', 'sail', 'electric', 'other',
];

/// Human label for a lower-case enum value (`fibreglass` → `Fibreglass`).
String enumLabel(String value) =>
    value.isEmpty ? value : value[0].toUpperCase() + value.substring(1);

/// A vessel in the user's garage (`VesselResponse`).
class Vessel {
  const Vessel({
    required this.id,
    required this.userId,
    required this.nickname,
    required this.make,
    required this.model,
    required this.year,
    required this.isPrimary,
    required this.createdAt,
    required this.updatedAt,
    this.hin,
    this.hinStatus,
    this.hinDecoded,
    this.modelYearId,
    this.hullType,
    this.lengthFt,
    this.primaryUse,
    this.propulsionType,
    this.engineMake,
    this.engineModel,
    this.engineYear,
    this.engineSerial,
    this.engineHours,
  });

  final String id;
  final String userId;
  final String nickname;
  final String make;
  final String model;
  final int year;
  final String? hin;
  final String? hinStatus;
  final Map<String, dynamic>? hinDecoded;
  final String? modelYearId;
  final String? hullType;
  final double? lengthFt;
  final String? primaryUse;
  final String? propulsionType;
  final String? engineMake;
  final String? engineModel;
  final int? engineYear;
  final String? engineSerial;
  final int? engineHours;
  final bool isPrimary;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// `2018 Haines Hunter SF600`.
  String get description => '$year $make $model';

  /// Same shape as the server's fitment label: `Sea Biscuit (2018 Haines Hunter SF600)`.
  String get label => '$nickname ($description)';

  bool get hasEngine => engineMake != null || engineModel != null;

  factory Vessel.fromJson(Map<String, dynamic> json) => Vessel(
        id: req<String>(json, 'id'),
        userId: req<String>(json, 'user_id'),
        nickname: req<String>(json, 'nickname'),
        hin: opt<String>(json, 'hin'),
        hinStatus: opt<String>(json, 'hin_status'),
        hinDecoded: optMap(json, 'hin_decoded'),
        make: req<String>(json, 'make'),
        model: req<String>(json, 'model'),
        year: req<int>(json, 'year'),
        modelYearId: opt<String>(json, 'model_year_id'),
        hullType: opt<String>(json, 'hull_type'),
        lengthFt: optDouble(json, 'length_ft'),
        primaryUse: opt<String>(json, 'primary_use'),
        propulsionType: opt<String>(json, 'propulsion_type'),
        engineMake: opt<String>(json, 'engine_make'),
        engineModel: opt<String>(json, 'engine_model'),
        engineYear: opt<int>(json, 'engine_year'),
        engineSerial: opt<String>(json, 'engine_serial'),
        engineHours: opt<int>(json, 'engine_hours'),
        isPrimary: req<bool>(json, 'is_primary'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

/// Form values for `VesselCreate` / `VesselUpdate`. Field names are the
/// canonical server names; the server rejects unknown fields with 422.
class VesselDraft {
  const VesselDraft({
    required this.nickname,
    required this.make,
    required this.model,
    required this.year,
    this.isPrimary = false,
    this.hin,
    this.hullType,
    this.lengthFt,
    this.primaryUse,
    this.propulsionType,
    this.engineMake,
    this.engineModel,
    this.engineYear,
    this.engineSerial,
    this.engineHours,
  });

  final String nickname;
  final String make;
  final String model;
  final int year;
  final bool isPrimary;
  final String? hin;
  final String? hullType;
  final double? lengthFt;
  final String? primaryUse;
  final String? propulsionType;
  final String? engineMake;
  final String? engineModel;
  final int? engineYear;
  final String? engineSerial;
  final int? engineHours;

  factory VesselDraft.fromVessel(Vessel v) => VesselDraft(
        nickname: v.nickname,
        make: v.make,
        model: v.model,
        year: v.year,
        isPrimary: v.isPrimary,
        hin: v.hin,
        hullType: v.hullType,
        lengthFt: v.lengthFt,
        primaryUse: v.primaryUse,
        propulsionType: v.propulsionType,
        engineMake: v.engineMake,
        engineModel: v.engineModel,
        engineYear: v.engineYear,
        engineSerial: v.engineSerial,
        engineHours: v.engineHours,
      );

  Map<String, dynamic> _optional() => {
        'hin': hin,
        'hull_type': hullType,
        'length_ft': lengthFt,
        'primary_use': primaryUse,
        'propulsion_type': propulsionType,
        'engine_make': engineMake,
        'engine_model': engineModel,
        'engine_year': engineYear,
        'engine_serial': engineSerial,
        'engine_hours': engineHours,
      };

  /// POST /vessels/ body. Empty optional fields are omitted.
  Map<String, dynamic> toCreateJson() => {
        'nickname': nickname,
        'make': make,
        'model': model,
        'year': year,
        'is_primary': isPrimary,
        ..._optional()..removeWhere((_, v) => v == null),
      };

  /// PATCH /vessels/{id} body. Optional fields are sent as null to clear them.
  Map<String, dynamic> toUpdateJson() => {
        'nickname': nickname,
        'make': make,
        'model': model,
        'year': year,
        'is_primary': isPrimary,
        ..._optional(),
      };
}
