import 'package:helm_marine/core/models/json.dart';

DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

double _num(Map<String, dynamic> json, String key) {
  final v = json[key];
  if (v is num) return v.toDouble();
  throw FormatException('Field "$key": expected number, got ${v.runtimeType}');
}

/// A product fitment rule in the admin review queue (`FitmentRuleAdminResponse`).
class FitmentRule {
  const FitmentRule({
    required this.id,
    required this.productId,
    required this.fitmentType,
    required this.verificationStatus,
    required this.confidenceScore,
    required this.createdAt,
    this.vesselMake,
    this.vesselModel,
    this.yearFrom,
    this.yearTo,
    this.engineMake,
    this.engineModel,
    this.engineYearFrom,
    this.engineYearTo,
    this.equipmentCategoryId,
    this.equipmentCategory,
    this.equipmentMake,
    this.equipmentModel,
    this.dataSource,
    this.sourceUrl,
    this.notes,
    this.verifiedAt,
    this.verifiedBy,
  });

  final String id;
  final String productId;
  final String? vesselMake;
  final String? vesselModel;
  final int? yearFrom;
  final int? yearTo;
  final String? engineMake;
  final String? engineModel;
  final int? engineYearFrom;
  final int? engineYearTo;
  final String? equipmentCategoryId;
  final String? equipmentCategory;
  final String? equipmentMake;
  final String? equipmentModel;
  final String fitmentType;

  /// `unverified`, `verified` or `rejected`.
  final String verificationStatus;
  final double confidenceScore;
  final String? dataSource;
  final String? sourceUrl;
  final String? notes;
  final DateTime? verifiedAt;
  final String? verifiedBy;
  final DateTime createdAt;

  static String _range(int? from, int? to) => switch ((from, to)) {
        (null, null) => '',
        (final f?, null) => ' ($f+)',
        (null, final t?) => ' (to $t)',
        (final f?, final t?) => ' ($f–$t)',
      };

  /// What the rule applies to, e.g. `Engine: Yamaha F150 (2015–2024)`.
  List<String> get scope => [
        if (vesselMake != null)
          'Vessel: ${[vesselMake, vesselModel].whereType<String>().join(' ')}${_range(yearFrom, yearTo)}',
        if (engineMake != null)
          'Engine: ${[engineMake, engineModel].whereType<String>().join(' ')}${_range(engineYearFrom, engineYearTo)}',
        if (equipmentCategory != null || equipmentMake != null)
          'Equipment: ${[equipmentCategory, equipmentMake, equipmentModel].whereType<String>().join(' ')}',
      ];

  factory FitmentRule.fromJson(Map<String, dynamic> json) => FitmentRule(
        id: req<String>(json, 'id'),
        productId: req<String>(json, 'product_id'),
        vesselMake: opt<String>(json, 'vessel_make'),
        vesselModel: opt<String>(json, 'vessel_model'),
        yearFrom: opt<int>(json, 'year_from'),
        yearTo: opt<int>(json, 'year_to'),
        engineMake: opt<String>(json, 'engine_make'),
        engineModel: opt<String>(json, 'engine_model'),
        engineYearFrom: opt<int>(json, 'engine_year_from'),
        engineYearTo: opt<int>(json, 'engine_year_to'),
        equipmentCategoryId: opt<String>(json, 'equipment_category_id'),
        equipmentCategory: opt<String>(json, 'equipment_category'),
        equipmentMake: opt<String>(json, 'equipment_make'),
        equipmentModel: opt<String>(json, 'equipment_model'),
        fitmentType: req<String>(json, 'fitment_type'),
        verificationStatus: req<String>(json, 'verification_status'),
        confidenceScore: _num(json, 'confidence_score'),
        dataSource: opt<String>(json, 'data_source'),
        sourceUrl: opt<String>(json, 'source_url'),
        notes: opt<String>(json, 'notes'),
        verifiedAt: _optDate(json, 'verified_at'),
        verifiedBy: opt<String>(json, 'verified_by'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// One equipment row attached to a verification request.
class VerificationEquipment {
  const VerificationEquipment({
    required this.id,
    required this.categoryName,
    required this.make,
    required this.verificationStatus,
    this.model,
    this.serialNumber,
    this.year,
  });

  final String id;
  final String categoryName;
  final String make;
  final String? model;
  final String? serialNumber;
  final int? year;
  final String verificationStatus;

  String get description => [make, model].whereType<String>().join(' ');

  factory VerificationEquipment.fromJson(Map<String, dynamic> json) {
    final category = optMap(json, 'category');
    return VerificationEquipment(
      id: req<String>(json, 'id'),
      categoryName: category == null ? 'Equipment' : (opt<String>(category, 'name') ?? req<String>(category, 'slug')),
      make: req<String>(json, 'make'),
      model: opt<String>(json, 'model'),
      serialNumber: opt<String>(json, 'serial_number'),
      year: opt<int>(json, 'year'),
      verificationStatus: req<String>(json, 'verification_status'),
    );
  }
}

/// An equipment-profile verification request (`AdminVerificationItem`, and the
/// `VerificationRequestResponse` returned by approve/reject).
class VerificationRequest {
  const VerificationRequest({
    required this.id,
    required this.vesselId,
    required this.userId,
    required this.status,
    required this.createdAt,
    this.vesselLabel,
    this.submittedNote,
    this.evidenceUrl,
    this.reviewedBy,
    this.reviewedAt,
    this.reviewNote,
    this.equipment = const [],
  });

  final String id;
  final String vesselId;
  final String userId;

  /// `pending`, `approved` or `rejected`.
  final String status;
  final String? vesselLabel;
  final String? submittedNote;
  final String? evidenceUrl;
  final String? reviewedBy;
  final DateTime? reviewedAt;
  final String? reviewNote;
  final DateTime createdAt;
  final List<VerificationEquipment> equipment;

  factory VerificationRequest.fromJson(Map<String, dynamic> json) => VerificationRequest(
        id: req<String>(json, 'id'),
        vesselId: req<String>(json, 'vessel_id'),
        userId: req<String>(json, 'user_id'),
        status: req<String>(json, 'status'),
        vesselLabel: opt<String>(json, 'vessel_label'),
        submittedNote: opt<String>(json, 'submitted_note'),
        evidenceUrl: opt<String>(json, 'evidence_url'),
        reviewedBy: opt<String>(json, 'reviewed_by'),
        reviewedAt: _optDate(json, 'reviewed_at'),
        reviewNote: opt<String>(json, 'review_note'),
        createdAt: reqDate(json, 'created_at'),
        equipment: [
          if (json['equipment'] != null)
            for (final e in mapList(json, 'equipment')) VerificationEquipment.fromJson(e),
        ],
      );
}

/// A knowledge corpus source (`KnowledgeSourceResponse`).
class KnowledgeSource {
  const KnowledgeSource({
    required this.id,
    required this.title,
    required this.licence,
    required this.licenceVerified,
    required this.admissionStatus,
    required this.isSynthetic,
    required this.domain,
    required this.appliesTo,
    required this.checksum,
    required this.chunkCount,
    required this.embeddingModels,
    required this.createdAt,
    required this.updatedAt,
    this.publisher,
    this.url,
    this.version,
    this.admittedBy,
    this.admittedAt,
  });

  final String id;
  final String title;
  final String? publisher;
  final String? url;
  final String licence;
  final bool licenceVerified;

  /// `pending`, `admitted` or `revoked`.
  final String admissionStatus;
  final bool isSynthetic;
  final String domain;
  final Map<String, dynamic> appliesTo;
  final String checksum;
  final String? version;
  final String? admittedBy;
  final DateTime? admittedAt;
  final int chunkCount;
  final List<String> embeddingModels;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get canAdmit => admissionStatus != 'admitted';
  bool get canRevoke => admissionStatus == 'admitted';

  factory KnowledgeSource.fromJson(Map<String, dynamic> json) => KnowledgeSource(
        id: req<String>(json, 'id'),
        title: req<String>(json, 'title'),
        publisher: opt<String>(json, 'publisher'),
        url: opt<String>(json, 'url'),
        licence: req<String>(json, 'licence'),
        licenceVerified: req<bool>(json, 'licence_verified'),
        admissionStatus: req<String>(json, 'admission_status'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        domain: req<String>(json, 'domain'),
        appliesTo: optMap(json, 'applies_to') ?? const {},
        checksum: req<String>(json, 'checksum'),
        version: opt<String>(json, 'version'),
        admittedBy: opt<String>(json, 'admitted_by'),
        admittedAt: _optDate(json, 'admitted_at'),
        chunkCount: opt<int>(json, 'chunk_count') ?? 0,
        embeddingModels: stringList(json, 'embedding_models'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

/// `KnowledgeIngestResponse`: `created`, `unchanged` or `new_version`.
class KnowledgeIngestResult {
  const KnowledgeIngestResult({required this.status, required this.source, required this.supersededSourceIds});

  final String status;
  final KnowledgeSource source;
  final List<String> supersededSourceIds;

  factory KnowledgeIngestResult.fromJson(Map<String, dynamic> json) => KnowledgeIngestResult(
        status: req<String>(json, 'status'),
        source: KnowledgeSource.fromJson(reqMap(json, 'source')),
        supersededSourceIds: stringList(json, 'superseded_source_ids'),
      );
}

/// `KnowledgeReembedResponse`.
class KnowledgeReembedResult {
  const KnowledgeReembedResult({required this.source, required this.chunksEmbedded});

  final KnowledgeSource source;
  final int chunksEmbedded;

  factory KnowledgeReembedResult.fromJson(Map<String, dynamic> json) => KnowledgeReembedResult(
        source: KnowledgeSource.fromJson(reqMap(json, 'source')),
        chunksEmbedded: req<int>(json, 'chunks_embedded'),
      );
}

/// Request body for `POST /knowledge/sources`.
class KnowledgeIngestDraft {
  const KnowledgeIngestDraft({
    required this.title,
    required this.licence,
    required this.domain,
    required this.content,
    this.publisher,
    this.url,
    this.licenceVerified = false,
    this.isSynthetic = false,
    this.format = 'markdown',
    this.version,
  });

  final String title;
  final String? publisher;
  final String? url;
  final String licence;
  final bool licenceVerified;
  final String domain;
  final bool isSynthetic;
  final String? version;

  /// `markdown` or `text`.
  final String format;
  final String content;

  Map<String, dynamic> toJson() => {
        'title': title,
        if (publisher != null && publisher!.isNotEmpty) 'publisher': publisher,
        if (url != null && url!.isNotEmpty) 'url': url,
        'licence': licence,
        'licence_verified': licenceVerified,
        'domain': domain,
        'is_synthetic': isSynthetic,
        if (version != null && version!.isNotEmpty) 'version': version,
        'format': format,
        'content': content,
      };
}

/// One privileged action from `GET /admin/audit`.
class AuditEntry {
  const AuditEntry({
    required this.id,
    required this.action,
    required this.entityType,
    required this.createdAt,
    this.actorId,
    this.entityId,
    this.detail,
  });

  final String id;
  final String? actorId;
  final String action;
  final String entityType;
  final String? entityId;
  final Map<String, dynamic>? detail;
  final DateTime createdAt;

  factory AuditEntry.fromJson(Map<String, dynamic> json) => AuditEntry(
        id: req<String>(json, 'id'),
        actorId: opt<String>(json, 'actor_id'),
        action: req<String>(json, 'action'),
        entityType: req<String>(json, 'entity_type'),
        entityId: opt<String>(json, 'entity_id'),
        detail: optMap(json, 'detail'),
        createdAt: reqDate(json, 'created_at'),
      );
}
