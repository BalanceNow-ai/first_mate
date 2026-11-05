/// Boat OEM database and HIN decoding contracts (`/boat-db/...`).
library;

import 'package:helm_marine/core/models/json.dart';

/// Result of `POST /boat-db/hin/decode`: a *suggestion* only. The manufacturer
/// is present only when its MIC is recorded; nothing is guessed.
class HinDecode {
  const HinDecode({
    required this.input,
    required this.valid,
    required this.status,
    required this.confidence,
    this.normalized,
    this.format,
    this.countryCode,
    this.mic,
    this.serial,
    this.productionMonth,
    this.productionYear,
    this.modelYear,
    this.manufacturer,
    this.warnings = const [],
    this.note,
  });

  final String input;
  final String? normalized;
  final bool valid;

  /// `valid` | `invalid` | `unrecognised`.
  final String status;
  final String? format;
  final String? countryCode;
  final String? mic;
  final String? serial;
  final int? productionMonth;
  final int? productionYear;
  final int? modelYear;
  final HinManufacturer? manufacturer;
  final double confidence;
  final List<String> warnings;

  /// Present on the copy stored with a vessel (`hin_decoded.note`).
  final String? note;

  bool get isInvalid => status == 'invalid';

  factory HinDecode.fromJson(Map<String, dynamic> json) {
    final maker = optMap(json, 'manufacturer');
    return HinDecode(
      input: req<String>(json, 'input'),
      normalized: opt<String>(json, 'normalized'),
      valid: req<bool>(json, 'valid'),
      status: req<String>(json, 'status'),
      format: opt<String>(json, 'format'),
      countryCode: opt<String>(json, 'country_code'),
      mic: opt<String>(json, 'mic'),
      serial: opt<String>(json, 'serial'),
      productionMonth: opt<int>(json, 'production_month'),
      productionYear: opt<int>(json, 'production_year'),
      modelYear: opt<int>(json, 'model_year'),
      manufacturer: maker == null ? null : HinManufacturer.fromJson(maker),
      confidence: optDouble(json, 'confidence') ?? 0,
      warnings: stringList(json, 'warnings'),
      note: opt<String>(json, 'note'),
    );
  }
}

class HinManufacturer {
  const HinManufacturer({required this.id, required this.name, required this.isSynthetic});

  final String id;
  final String name;
  final bool isSynthetic;

  factory HinManufacturer.fromJson(Map<String, dynamic> json) => HinManufacturer(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
      );
}

/// `ManufacturerResponse`.
class BoatManufacturer {
  const BoatManufacturer({
    required this.id,
    required this.name,
    required this.isSynthetic,
    this.country,
    this.website,
    this.micCodes = const [],
    this.source,
    this.modelCount = 0,
  });

  final String id;
  final String name;
  final String? country;
  final String? website;
  final List<String> micCodes;
  final bool isSynthetic;
  final String? source;
  final int modelCount;

  factory BoatManufacturer.fromJson(Map<String, dynamic> json) => BoatManufacturer(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        country: opt<String>(json, 'country'),
        website: opt<String>(json, 'website'),
        micCodes: stringList(json, 'mic_codes'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        source: opt<String>(json, 'source'),
        modelCount: opt<int>(json, 'model_count') ?? 0,
      );
}

/// `BoatModelResponse`.
class BoatModel {
  const BoatModel({
    required this.id,
    required this.manufacturerId,
    required this.name,
    required this.isSynthetic,
    this.hullType,
    this.propulsionType,
    this.lengthFt,
    this.beamIn,
    this.sourceUrl,
    this.years = const [],
  });

  final String id;
  final String manufacturerId;
  final String name;
  final String? hullType;
  final String? propulsionType;
  final double? lengthFt;
  final int? beamIn;
  final bool isSynthetic;
  final String? sourceUrl;
  final List<int> years;

  factory BoatModel.fromJson(Map<String, dynamic> json) => BoatModel(
        id: req<String>(json, 'id'),
        manufacturerId: req<String>(json, 'manufacturer_id'),
        name: req<String>(json, 'name'),
        hullType: opt<String>(json, 'hull_type'),
        propulsionType: opt<String>(json, 'propulsion_type'),
        lengthFt: optDouble(json, 'length_ft'),
        beamIn: opt<int>(json, 'beam_in'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        sourceUrl: opt<String>(json, 'source_url'),
        years: [for (final y in (json['years'] as List? ?? const [])) y as int],
      );
}

/// `ModelYearResponse`.
class BoatModelYear {
  const BoatModelYear({
    required this.id,
    required this.boatModelId,
    required this.year,
    this.brochureUrl,
    this.hinPrefix,
    this.equipmentCount = 0,
  });

  final String id;
  final String boatModelId;
  final int year;
  final String? brochureUrl;
  final String? hinPrefix;
  final int equipmentCount;

  factory BoatModelYear.fromJson(Map<String, dynamic> json) => BoatModelYear(
        id: req<String>(json, 'id'),
        boatModelId: req<String>(json, 'boat_model_id'),
        year: req<int>(json, 'year'),
        brochureUrl: opt<String>(json, 'brochure_url'),
        hinPrefix: opt<String>(json, 'hin_prefix'),
        equipmentCount: opt<int>(json, 'equipment_count') ?? 0,
      );
}

/// `EquipmentCategoryResponse`.
class EquipmentCategory {
  const EquipmentCategory({required this.id, required this.slug, required this.name, this.parentId});

  final String id;
  final String slug;
  final String name;
  final String? parentId;

  factory EquipmentCategory.fromJson(Map<String, dynamic> json) => EquipmentCategory(
        id: req<String>(json, 'id'),
        slug: req<String>(json, 'slug'),
        name: req<String>(json, 'name'),
        parentId: opt<String>(json, 'parent_id'),
      );
}

/// `OEMEquipmentResponse` — factory equipment recorded for a model year.
class OemEquipment {
  const OemEquipment({
    required this.id,
    required this.modelYearId,
    required this.category,
    required this.equipmentMake,
    required this.isStandard,
    required this.dataSource,
    required this.confidenceScore,
    required this.verificationStatus,
    required this.isSynthetic,
    required this.reliable,
    this.equipmentModel,
    this.partSku,
    this.sourceUrl,
  });

  final String id;
  final String modelYearId;
  final EquipmentCategory category;
  final String equipmentMake;
  final String? equipmentModel;
  final String? partSku;
  final bool isStandard;
  final String dataSource;
  final String? sourceUrl;
  final double confidenceScore;
  final String verificationStatus;
  final bool isSynthetic;

  /// True only when confident enough to be presented as fact.
  final bool reliable;

  factory OemEquipment.fromJson(Map<String, dynamic> json) => OemEquipment(
        id: req<String>(json, 'id'),
        modelYearId: req<String>(json, 'model_year_id'),
        category: EquipmentCategory.fromJson(reqMap(json, 'category')),
        equipmentMake: req<String>(json, 'equipment_make'),
        equipmentModel: opt<String>(json, 'equipment_model'),
        partSku: opt<String>(json, 'part_sku'),
        isStandard: req<bool>(json, 'is_standard'),
        dataSource: req<String>(json, 'data_source'),
        sourceUrl: opt<String>(json, 'source_url'),
        confidenceScore: optDouble(json, 'confidence_score') ?? 0,
        verificationStatus: req<String>(json, 'verification_status'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        reliable: req<bool>(json, 'reliable'),
      );
}

/// `ModelYearDetail` — a model year with its manufacturer, model and OEM equipment.
class BoatModelYearDetail extends BoatModelYear {
  const BoatModelYearDetail({
    required super.id,
    required super.boatModelId,
    required super.year,
    super.brochureUrl,
    super.hinPrefix,
    super.equipmentCount,
    required this.manufacturer,
    required this.boatModel,
    this.equipment = const [],
  });

  final BoatManufacturer manufacturer;
  final BoatModel boatModel;
  final List<OemEquipment> equipment;

  bool get isSynthetic => manufacturer.isSynthetic || boatModel.isSynthetic;

  /// `Synthetic Test Marine (fixture) Fixture 600 Runabout 2021`.
  String get label => '${manufacturer.name} ${boatModel.name} $year';

  factory BoatModelYearDetail.fromJson(Map<String, dynamic> json) {
    final base = BoatModelYear.fromJson(json);
    return BoatModelYearDetail(
      id: base.id,
      boatModelId: base.boatModelId,
      year: base.year,
      brochureUrl: base.brochureUrl,
      hinPrefix: base.hinPrefix,
      equipmentCount: base.equipmentCount,
      manufacturer: BoatManufacturer.fromJson(reqMap(json, 'manufacturer')),
      boatModel: BoatModel.fromJson(reqMap(json, 'boat_model')),
      equipment: [for (final e in mapList(json, 'equipment')) OemEquipment.fromJson(e)],
    );
  }
}
