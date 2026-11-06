/// Typed models for the service-jobs API (`/service-jobs/*`, `/service-assets/*`).
///
/// Every model parses the server's response exactly (see
/// `backend/app/schemas/service_jobs.py`, `service_assets.py`,
/// `service_preparation.py`, `service_feedback.py`); a missing or wrongly typed
/// required field throws a [FormatException] so contract drift fails in tests.
/// Decimal values (measurements, quantities) stay strings exactly as stored;
/// money is integer minor units with a currency code. Storage keys are never
/// part of any contract.
library;

import 'package:helm_marine/core/models/json.dart';

List<T> _list<T>(Map<String, dynamic> json, String key, T Function(Map<String, dynamic>) f) =>
    [for (final m in mapList(json, key)) f(m)];

DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

// ============================================================== jobs and viewer
class Viewer {
  const Viewer({
    required this.role,
    required this.sections,
    required this.restrictedAccess,
    this.organizationId,
    this.assignmentId,
  });

  final String role;
  final List<String> sections;
  final String? organizationId;
  final String? assignmentId;
  final bool restrictedAccess;

  bool get isOwner => role == 'owner';
  bool can(String section) => sections.contains(section);

  factory Viewer.fromJson(Map<String, dynamic> json) => Viewer(
        role: req<String>(json, 'role'),
        sections: stringList(json, 'sections'),
        organizationId: opt<String>(json, 'organization_id'),
        assignmentId: opt<String>(json, 'assignment_id'),
        restrictedAccess: req<bool>(json, 'restricted_access'),
      );
}

class EvidenceRequest {
  const EvidenceRequest({
    required this.id,
    required this.jobId,
    required this.requesterRole,
    required this.category,
    required this.prompt,
    required this.reason,
    required this.priority,
    required this.status,
    required this.technicianInspectionRequired,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    required this.options,
    this.organizationId,
    this.component,
    this.measurementDimension,
    this.unavailableReason,
    this.answerNote,
    this.answeredAt,
  });

  final String id;
  final String jobId;
  final String requesterRole;
  final String? organizationId;
  final String category;
  final String? component;
  final String prompt;
  final String reason;
  final String? measurementDimension;
  final String priority;
  final String status;
  final String? unavailableReason;
  final bool technicianInspectionRequired;
  final String? answerNote;
  final DateTime? answeredAt;
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<String> options;

  bool get isOutstanding => status == 'outstanding';

  factory EvidenceRequest.fromJson(Map<String, dynamic> json) => EvidenceRequest(
        id: req<String>(json, 'id'),
        jobId: req<String>(json, 'job_id'),
        requesterRole: req<String>(json, 'requester_role'),
        organizationId: opt<String>(json, 'organization_id'),
        category: req<String>(json, 'category'),
        component: opt<String>(json, 'component'),
        prompt: req<String>(json, 'prompt'),
        reason: req<String>(json, 'reason'),
        measurementDimension: opt<String>(json, 'measurement_dimension'),
        priority: req<String>(json, 'priority'),
        status: req<String>(json, 'status'),
        unavailableReason: opt<String>(json, 'unavailable_reason'),
        technicianInspectionRequired: req<bool>(json, 'technician_inspection_required'),
        answerNote: opt<String>(json, 'answer_note'),
        answeredAt: _optDate(json, 'answered_at'),
        version: req<int>(json, 'version'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
        options: stringList(json, 'options'),
      );
}

class EvidenceSummary {
  const EvidenceSummary({
    required this.outstanding,
    required this.answered,
    required this.unavailable,
    required this.waived,
    required this.availableAssetCount,
  });

  final List<EvidenceRequest> outstanding;
  final List<EvidenceRequest> answered;
  final List<EvidenceRequest> unavailable;
  final List<EvidenceRequest> waived;
  final int availableAssetCount;

  int get total => outstanding.length + answered.length + unavailable.length + waived.length;

  factory EvidenceSummary.fromJson(Map<String, dynamic> json) => EvidenceSummary(
        outstanding: _list(json, 'outstanding', EvidenceRequest.fromJson),
        answered: _list(json, 'answered', EvidenceRequest.fromJson),
        unavailable: _list(json, 'unavailable', EvidenceRequest.fromJson),
        waived: _list(json, 'waived', EvidenceRequest.fromJson),
        availableAssetCount: req<int>(json, 'available_asset_count'),
      );
}

/// A visible gap: something the owner could not (safely) provide.
class EvidenceGap {
  const EvidenceGap({
    required this.requestId,
    required this.category,
    required this.prompt,
    required this.technicianInspectionRequired,
    this.component,
    this.reason,
    this.note,
  });

  final String requestId;
  final String category;
  final String? component;
  final String prompt;
  final String? reason;
  final String? note;
  final bool technicianInspectionRequired;

  factory EvidenceGap.fromJson(Map<String, dynamic> json) => EvidenceGap(
        requestId: req<String>(json, 'request_id'),
        category: req<String>(json, 'category'),
        component: opt<String>(json, 'component'),
        prompt: req<String>(json, 'prompt'),
        reason: opt<String>(json, 'reason'),
        note: opt<String>(json, 'note'),
        technicianInspectionRequired: req<bool>(json, 'technician_inspection_required'),
      );
}

class OrganizationRef {
  const OrganizationRef({required this.id, required this.name, this.tradingName});

  final String id;
  final String name;
  final String? tradingName;

  String get displayName =>
      tradingName == null || tradingName!.isEmpty || tradingName == name ? name : '$name ($tradingName)';

  factory OrganizationRef.fromJson(Map<String, dynamic> json) => OrganizationRef(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        tradingName: opt<String>(json, 'trading_name'),
      );
}

class AssignmentMember {
  const AssignmentMember({required this.userId, required this.restrictedAccess, required this.addedAt, this.name});

  final String userId;
  final String? name;
  final bool restrictedAccess;
  final DateTime addedAt;

  factory AssignmentMember.fromJson(Map<String, dynamic> json) => AssignmentMember(
        userId: req<String>(json, 'user_id'),
        name: opt<String>(json, 'name'),
        restrictedAccess: req<bool>(json, 'restricted_access'),
        addedAt: reqDate(json, 'added_at'),
      );
}

class Assignment {
  const Assignment({
    required this.id,
    required this.jobId,
    required this.organization,
    required this.status,
    required this.sections,
    required this.liveUpdates,
    required this.invitedAt,
    required this.version,
    required this.members,
    this.acceptedAt,
    this.revokedAt,
  });

  final String id;
  final String jobId;
  final OrganizationRef organization;
  final String status;
  final List<String> sections;
  final bool liveUpdates;
  final DateTime invitedAt;
  final DateTime? acceptedAt;
  final DateTime? revokedAt;
  final int version;
  final List<AssignmentMember> members;

  bool get isLive => status == 'invited' || status == 'accepted';

  factory Assignment.fromJson(Map<String, dynamic> json) => Assignment(
        id: req<String>(json, 'id'),
        jobId: req<String>(json, 'job_id'),
        organization: OrganizationRef.fromJson(reqMap(json, 'organization')),
        status: req<String>(json, 'status'),
        sections: stringList(json, 'sections'),
        liveUpdates: req<bool>(json, 'live_updates'),
        invitedAt: reqDate(json, 'invited_at'),
        acceptedAt: _optDate(json, 'accepted_at'),
        revokedAt: _optDate(json, 'revoked_at'),
        version: req<int>(json, 'version'),
        members: _list(json, 'members', AssignmentMember.fromJson),
      );
}

/// The vessel/equipment snapshot taken when the job was created, which the
/// owner confirms or corrects explicitly.
class VesselContext {
  const VesselContext({
    required this.vessel,
    required this.engine,
    required this.equipment,
    required this.ownerConfirmed,
    required this.corrections,
    required this.uncertainCategories,
  });

  final Map<String, dynamic> vessel;
  final Map<String, dynamic>? engine;
  final List<Map<String, dynamic>> equipment;
  final bool ownerConfirmed;
  final List<Map<String, dynamic>> corrections;
  final List<String> uncertainCategories;

  String? get nickname => vessel['nickname'] as String?;

  String get vesselLine => [vessel['make'], vessel['model'], vessel['year']]
      .where((v) => v != null && '$v'.isNotEmpty)
      .join(' ');

  String? get engineLine {
    final e = engine;
    if (e == null) return null;
    final parts = [e['make'], e['model'], e['year']].where((v) => v != null && '$v'.isNotEmpty).join(' ');
    return parts.isEmpty ? null : parts;
  }

  factory VesselContext.fromJson(Map<String, dynamic> json) => VesselContext(
        vessel: optMap(json, 'vessel') ?? const {},
        engine: optMap(json, 'engine'),
        equipment: json['equipment'] == null ? const [] : mapList(json, 'equipment'),
        ownerConfirmed: opt<bool>(json, 'owner_confirmed') ?? false,
        corrections: json['corrections'] == null ? const [] : mapList(json, 'corrections'),
        uncertainCategories: stringList(json, 'uncertain_categories'),
      );
}

class ServiceJob {
  const ServiceJob({
    required this.id,
    required this.entryPoint,
    required this.title,
    required this.status,
    required this.version,
    required this.evidenceRevision,
    required this.disputed,
    required this.createdAt,
    required this.updatedAt,
    required this.viewer,
    this.vesselId,
    this.archivedAt,
    this.snapshotState,
    this.snapshotBriefId,
    this.snapshotPublishedAt,
    this.issueDescription,
    this.affectedSystem,
    this.affectedEquipment,
    this.occursWhen,
    this.alreadyTried,
    this.urgency,
    this.vesselContext,
    this.evidence,
    this.gaps,
    this.technicianInspectionRequired,
    this.assignment,
  });

  final String id;
  final String? vesselId;
  final String entryPoint;
  final String title;
  final String status;
  final int version;
  final int evidenceRevision;
  final bool disputed;
  final DateTime? archivedAt;
  final DateTime createdAt;
  final DateTime updatedAt;
  final Viewer viewer;

  /// Where the job content comes from for this reader: `live` (the owner, or live
  /// updates on), `brief` (as of the latest published brief) or
  /// `no_brief_published` (live updates off and nothing published: header only).
  final String? snapshotState;
  final String? snapshotBriefId;
  final DateTime? snapshotPublishedAt;
  final String? issueDescription;
  final String? affectedSystem;
  final String? affectedEquipment;
  final String? occursWhen;
  final String? alreadyTried;
  final String? urgency;
  final VesselContext? vesselContext;
  final EvidenceSummary? evidence;
  final List<EvidenceGap>? gaps;
  final bool? technicianInspectionRequired;
  final Assignment? assignment;

  bool get isClosed => const {'completed', 'archived', 'cancelled'}.contains(status);

  /// Live updates are off and the owner has not published a brief yet.
  bool get awaitingBrief => snapshotState == 'no_brief_published';

  /// The content shown is as of a published brief (live updates off).
  bool get showsBriefSnapshot => snapshotState == 'brief';

  factory ServiceJob.fromJson(Map<String, dynamic> json) {
    final ctx = optMap(json, 'vessel_context');
    final ev = optMap(json, 'evidence');
    final asg = optMap(json, 'assignment');
    return ServiceJob(
      id: req<String>(json, 'id'),
      vesselId: opt<String>(json, 'vessel_id'),
      entryPoint: req<String>(json, 'entry_point'),
      title: req<String>(json, 'title'),
      status: req<String>(json, 'status'),
      version: req<int>(json, 'version'),
      evidenceRevision: req<int>(json, 'evidence_revision'),
      disputed: req<bool>(json, 'disputed'),
      archivedAt: _optDate(json, 'archived_at'),
      createdAt: reqDate(json, 'created_at'),
      updatedAt: reqDate(json, 'updated_at'),
      viewer: Viewer.fromJson(reqMap(json, 'viewer')),
      snapshotState: opt<String>(json, 'snapshot_state'),
      snapshotBriefId: opt<String>(json, 'snapshot_brief_id'),
      snapshotPublishedAt: _optDate(json, 'snapshot_published_at'),
      issueDescription: opt<String>(json, 'issue_description'),
      affectedSystem: opt<String>(json, 'affected_system'),
      affectedEquipment: opt<String>(json, 'affected_equipment'),
      occursWhen: opt<String>(json, 'occurs_when'),
      alreadyTried: opt<String>(json, 'already_tried'),
      urgency: opt<String>(json, 'urgency'),
      vesselContext: ctx == null ? null : VesselContext.fromJson(ctx),
      evidence: ev == null ? null : EvidenceSummary.fromJson(ev),
      gaps: json['gaps'] == null ? null : _list(json, 'gaps', EvidenceGap.fromJson),
      technicianInspectionRequired: opt<bool>(json, 'technician_inspection_required'),
      assignment: asg == null ? null : Assignment.fromJson(asg),
    );
  }
}

class JobListItem {
  const JobListItem({
    required this.id,
    required this.title,
    required this.status,
    required this.urgency,
    required this.version,
    required this.outstandingRequests,
    required this.gapCount,
    required this.createdAt,
    required this.updatedAt,
    this.vesselId,
    this.assignmentStatus,
  });

  final String id;
  final String? vesselId;
  final String title;
  final String status;
  final String urgency;
  final int version;
  final int outstandingRequests;
  final int gapCount;
  final String? assignmentStatus;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory JobListItem.fromJson(Map<String, dynamic> json) => JobListItem(
        id: req<String>(json, 'id'),
        vesselId: opt<String>(json, 'vessel_id'),
        title: req<String>(json, 'title'),
        status: req<String>(json, 'status'),
        urgency: req<String>(json, 'urgency'),
        version: req<int>(json, 'version'),
        outstandingRequests: req<int>(json, 'outstanding_requests'),
        gapCount: req<int>(json, 'gap_count'),
        assignmentStatus: opt<String>(json, 'assignment_status'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

/// Fields for creating a job (`JobCreate`).
class JobDraft {
  const JobDraft({
    required this.vesselId,
    required this.title,
    this.entryPoint = 'vessel',
    this.issueDescription = '',
    this.affectedSystem,
    this.affectedEquipment,
    this.occursWhen,
    this.alreadyTried,
    this.urgency = 'unknown',
  });

  final String vesselId;
  final String entryPoint;
  final String title;
  final String issueDescription;
  final String? affectedSystem;
  final String? affectedEquipment;
  final String? occursWhen;
  final String? alreadyTried;
  final String urgency;

  static String? _clean(String? v) => v == null || v.trim().isEmpty ? null : v.trim();

  Map<String, dynamic> toJson() => {
        'vessel_id': vesselId,
        'entry_point': entryPoint,
        'title': title.trim(),
        'issue_description': issueDescription.trim(),
        if (_clean(affectedSystem) != null) 'affected_system': _clean(affectedSystem),
        if (_clean(affectedEquipment) != null) 'affected_equipment': _clean(affectedEquipment),
        if (_clean(occursWhen) != null) 'occurs_when': _clean(occursWhen),
        if (_clean(alreadyTried) != null) 'already_tried': _clean(alreadyTried),
        'urgency': urgency,
      };
}

// ============================================================== guided capture
class GuidanceProposal {
  const GuidanceProposal({
    required this.key,
    required this.category,
    required this.prompt,
    required this.reason,
    required this.priority,
    required this.safetyNote,
    required this.options,
    this.component,
    this.measurementDimension,
  });

  final String key;
  final String category;
  final String? component;
  final String prompt;
  final String reason;
  final String priority;
  final String? measurementDimension;
  final String safetyNote;
  final List<String> options;

  factory GuidanceProposal.fromJson(Map<String, dynamic> json) => GuidanceProposal(
        key: req<String>(json, 'key'),
        category: req<String>(json, 'category'),
        component: opt<String>(json, 'component'),
        prompt: req<String>(json, 'prompt'),
        reason: req<String>(json, 'reason'),
        priority: req<String>(json, 'priority'),
        measurementDimension: opt<String>(json, 'measurement_dimension'),
        safetyNote: req<String>(json, 'safety_note'),
        options: stringList(json, 'options'),
      );
}

/// The next useful step: an outstanding request, else a proposal, else done.
class NextEvidence {
  const NextEvidence({required this.complete, required this.message, required this.gaps, this.request, this.proposal});

  final EvidenceRequest? request;
  final GuidanceProposal? proposal;
  final bool complete;
  final String message;
  final List<EvidenceGap> gaps;

  factory NextEvidence.fromJson(Map<String, dynamic> json) {
    final r = optMap(json, 'request');
    final p = optMap(json, 'proposal');
    return NextEvidence(
      request: r == null ? null : EvidenceRequest.fromJson(r),
      proposal: p == null ? null : GuidanceProposal.fromJson(p),
      complete: req<bool>(json, 'complete'),
      message: req<String>(json, 'message'),
      gaps: _list(json, 'gaps', EvidenceGap.fromJson),
    );
  }
}

/// `AccessGeneralResponse` / `AccessRestrictedResponse`: the field values (strings).
class AccessDetails {
  const AccessDetails({required this.jobId, required this.values, required this.version, required this.updatedAt});

  final String jobId;
  final Map<String, String?> values;
  final int version;
  final DateTime updatedAt;

  factory AccessDetails.fromJson(Map<String, dynamic> json, String key) => AccessDetails(
        jobId: req<String>(json, 'job_id'),
        values: {for (final e in reqMap(json, key).entries) e.key: e.value as String?},
        version: req<int>(json, 'version'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

// ============================================================== sharing
class SectionPreview {
  const SectionPreview({
    required this.section,
    required this.label,
    required this.exposes,
    required this.counts,
    this.note,
  });

  final String section;
  final String label;
  final List<String> exposes;
  final Map<String, int> counts;
  final String? note;

  factory SectionPreview.fromJson(Map<String, dynamic> json) => SectionPreview(
        section: req<String>(json, 'section'),
        label: req<String>(json, 'label'),
        exposes: stringList(json, 'exposes'),
        counts: {for (final e in reqMap(json, 'counts').entries) e.key: e.value as int},
        note: opt<String>(json, 'note'),
      );
}

class SharingPreview {
  const SharingPreview({
    required this.organization,
    required this.sections,
    required this.withheld,
    required this.liveUpdates,
    required this.liveUpdatesNote,
  });

  final OrganizationRef organization;
  final List<SectionPreview> sections;
  final List<String> withheld;
  final bool liveUpdates;
  final String liveUpdatesNote;

  factory SharingPreview.fromJson(Map<String, dynamic> json) => SharingPreview(
        organization: OrganizationRef.fromJson(reqMap(json, 'organization')),
        sections: _list(json, 'sections', SectionPreview.fromJson),
        withheld: stringList(json, 'withheld'),
        liveUpdates: req<bool>(json, 'live_updates'),
        liveUpdatesNote: req<String>(json, 'live_updates_note'),
      );
}

// ============================================================== media
class ServiceAsset {
  const ServiceAsset({
    required this.id,
    required this.purpose,
    required this.status,
    required this.uploadedByRole,
    required this.uploadedByMe,
    required this.maxBytes,
    required this.quality,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    this.jobId,
    this.evidenceRequestId,
    this.caption,
    this.detectedType,
    this.sizeBytes,
    this.width,
    this.height,
    this.pages,
    this.duplicateOfId,
    this.rejectionReason,
    this.uploadExpiresAt,
  });

  final String id;
  final String? jobId;
  final String purpose;
  final String status;
  final String uploadedByRole;
  final bool uploadedByMe;
  final String? evidenceRequestId;
  final String? caption;
  final String? detectedType;
  final int? sizeBytes;
  final int maxBytes;
  final int? width;
  final int? height;
  final int? pages;
  final Map<String, dynamic> quality;
  final String? duplicateOfId;
  final String? rejectionReason;
  final DateTime? uploadExpiresAt;
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Still moving through upload → quarantine → processing.
  bool get inProgress => const {'upload_pending', 'quarantined', 'processing'}.contains(status);
  bool get isAvailable => status == 'available';

  factory ServiceAsset.fromJson(Map<String, dynamic> json) => ServiceAsset(
        id: req<String>(json, 'id'),
        jobId: opt<String>(json, 'job_id'),
        purpose: req<String>(json, 'purpose'),
        status: req<String>(json, 'status'),
        uploadedByRole: req<String>(json, 'uploaded_by_role'),
        uploadedByMe: req<bool>(json, 'uploaded_by_me'),
        evidenceRequestId: opt<String>(json, 'evidence_request_id'),
        caption: opt<String>(json, 'caption'),
        detectedType: opt<String>(json, 'detected_type'),
        sizeBytes: opt<int>(json, 'size_bytes'),
        maxBytes: req<int>(json, 'max_bytes'),
        width: opt<int>(json, 'width'),
        height: opt<int>(json, 'height'),
        pages: opt<int>(json, 'pages'),
        quality: reqMap(json, 'quality'),
        duplicateOfId: opt<String>(json, 'duplicate_of_id'),
        rejectionReason: opt<String>(json, 'rejection_reason'),
        uploadExpiresAt: _optDate(json, 'upload_expires_at'),
        version: req<int>(json, 'version'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

class UploadInstruction {
  const UploadInstruction({required this.method, required this.url, required this.maxBytes, this.expiresAt});

  final String method;
  final String url;
  final int maxBytes;
  final DateTime? expiresAt;

  factory UploadInstruction.fromJson(Map<String, dynamic> json) => UploadInstruction(
        method: req<String>(json, 'method'),
        url: req<String>(json, 'url'),
        maxBytes: req<int>(json, 'max_bytes'),
        expiresAt: _optDate(json, 'expires_at'),
      );
}

class AssetIntent {
  const AssetIntent({required this.asset, this.upload});

  final ServiceAsset asset;
  final UploadInstruction? upload;

  factory AssetIntent.fromJson(Map<String, dynamic> json) {
    final u = optMap(json, 'upload');
    return AssetIntent(
      asset: ServiceAsset.fromJson(reqMap(json, 'asset')),
      upload: u == null ? null : UploadInstruction.fromJson(u),
    );
  }
}

class AssetList {
  const AssetList({required this.items, required this.total});

  final List<ServiceAsset> items;
  final int total;

  factory AssetList.fromJson(Map<String, dynamic> json) =>
      AssetList(items: _list(json, 'items', ServiceAsset.fromJson), total: req<int>(json, 'total'));
}

class DownloadLink {
  const DownloadLink({required this.url, required this.expiresAt, required this.variant});

  final String url;
  final DateTime expiresAt;
  final String variant;

  factory DownloadLink.fromJson(Map<String, dynamic> json) => DownloadLink(
        url: req<String>(json, 'url'),
        expiresAt: reqDate(json, 'expires_at'),
        variant: req<String>(json, 'variant'),
      );
}

// ============================================================== analysis and observations
class AnalysisRun {
  const AnalysisRun({
    required this.id,
    required this.kind,
    required this.status,
    required this.assetIds,
    required this.observationCount,
    required this.attempts,
    required this.createdAt,
    required this.updatedAt,
    this.jobId,
    this.provider,
    this.model,
    this.jobRevision,
    this.supersededReason,
    this.error,
  });

  final String id;
  final String? jobId;
  final String kind;
  final String status;
  final String? provider;
  final String? model;
  final int? jobRevision;
  final List<String> assetIds;
  final int observationCount;
  final String? supersededReason;
  final String? error;
  final int attempts;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get inProgress => status == 'pending' || status == 'running';

  factory AnalysisRun.fromJson(Map<String, dynamic> json) => AnalysisRun(
        id: req<String>(json, 'id'),
        jobId: opt<String>(json, 'job_id'),
        kind: req<String>(json, 'kind'),
        status: req<String>(json, 'status'),
        provider: opt<String>(json, 'provider'),
        model: opt<String>(json, 'model'),
        jobRevision: opt<int>(json, 'job_revision'),
        assetIds: stringList(json, 'asset_ids'),
        observationCount: req<int>(json, 'observation_count'),
        supersededReason: opt<String>(json, 'superseded_reason'),
        error: opt<String>(json, 'error'),
        attempts: req<int>(json, 'attempts'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

class AnalysisStatus {
  const AnalysisStatus({
    required this.available,
    required this.provider,
    required this.substitute,
    required this.runs,
    this.message,
  });

  final bool available;
  final String provider;
  final String? message;
  final bool substitute;
  final List<AnalysisRun> runs;

  factory AnalysisStatus.fromJson(Map<String, dynamic> json) => AnalysisStatus(
        available: req<bool>(json, 'available'),
        provider: req<String>(json, 'provider'),
        message: opt<String>(json, 'message'),
        substitute: req<bool>(json, 'substitute'),
        runs: _list(json, 'runs', AnalysisRun.fromJson),
      );
}

class Observation {
  const Observation({
    required this.id,
    required this.jobId,
    required this.kind,
    required this.assertion,
    required this.state,
    required this.origin,
    required this.jobRevision,
    required this.isMeasurement,
    required this.createdAt,
    this.assetId,
    this.page,
    this.region,
    this.extractedText,
    this.confidence,
    this.uncertainty,
    this.analysisRunId,
    this.modelVersion,
    this.recordedBy,
    this.supersedesId,
    this.supersededById,
  });

  final String id;
  final String jobId;
  final String? assetId;
  final int? page;
  final Map<String, dynamic>? region;
  final String kind;
  final String assertion;
  final String? extractedText;
  final String state;
  final double? confidence;
  final String? uncertainty;
  final String origin;
  final String? analysisRunId;
  final String? modelVersion;
  final String? recordedBy;
  final String? supersedesId;
  final String? supersededById;
  final int jobRevision;
  final bool isMeasurement;
  final DateTime createdAt;

  bool get isActive => !const {'rejected', 'superseded'}.contains(state);

  factory Observation.fromJson(Map<String, dynamic> json) => Observation(
        id: req<String>(json, 'id'),
        jobId: req<String>(json, 'job_id'),
        assetId: opt<String>(json, 'asset_id'),
        page: opt<int>(json, 'page'),
        region: optMap(json, 'region'),
        kind: req<String>(json, 'kind'),
        assertion: req<String>(json, 'assertion'),
        extractedText: opt<String>(json, 'extracted_text'),
        state: req<String>(json, 'state'),
        confidence: optDouble(json, 'confidence'),
        uncertainty: opt<String>(json, 'uncertainty'),
        origin: req<String>(json, 'origin'),
        analysisRunId: opt<String>(json, 'analysis_run_id'),
        modelVersion: opt<String>(json, 'model_version'),
        recordedBy: opt<String>(json, 'recorded_by'),
        supersedesId: opt<String>(json, 'supersedes_id'),
        supersededById: opt<String>(json, 'superseded_by_id'),
        jobRevision: req<int>(json, 'job_revision'),
        isMeasurement: opt<bool>(json, 'is_measurement') ?? false,
        createdAt: reqDate(json, 'created_at'),
      );
}

// ============================================================== measurements
class Provenance {
  const Provenance({
    required this.badge,
    required this.label,
    required this.recordedByRole,
    required this.method,
    this.recordedBy,
    this.otherOrganization = false,
  });

  final String badge;
  final String label;
  final String? recordedBy;
  final String recordedByRole;
  final String method;

  /// Recorded or confirmed by another contractor organisation (identities withheld).
  final bool otherOrganization;

  factory Provenance.fromJson(Map<String, dynamic> json) => Provenance(
        badge: req<String>(json, 'badge'),
        label: req<String>(json, 'label'),
        recordedBy: opt<String>(json, 'recorded_by'),
        recordedByRole: req<String>(json, 'recorded_by_role'),
        method: req<String>(json, 'method'),
        otherOrganization: opt<bool>(json, 'other_organization') ?? false,
      );
}

class Confirmation {
  const Confirmation({this.confirmedBy, this.confirmedAt, this.method});

  final String? confirmedBy;
  final DateTime? confirmedAt;
  final String? method;

  factory Confirmation.fromJson(Map<String, dynamic> json) => Confirmation(
        confirmedBy: opt<String>(json, 'confirmed_by'),
        confirmedAt: _optDate(json, 'confirmed_at'),
        method: opt<String>(json, 'method'),
      );
}

class ThreadParts {
  const ThreadParts({this.standard, this.size, this.pitch});

  final String? standard;
  final String? size;
  final String? pitch;

  factory ThreadParts.fromJson(Map<String, dynamic> json) => ThreadParts(
        standard: opt<String>(json, 'standard'),
        size: opt<String>(json, 'size'),
        pitch: opt<String>(json, 'pitch'),
      );
}

class Measurement {
  const Measurement({
    required this.id,
    required this.jobId,
    required this.dimension,
    required this.component,
    required this.method,
    required this.state,
    required this.provenance,
    required this.isCurrent,
    required this.jobRevision,
    required this.createdAt,
    this.valueText,
    this.valueMin,
    this.valueMax,
    this.unit,
    this.normalizedMinMm,
    this.normalizedMaxMm,
    this.resolutionMm,
    this.precision,
    this.tool,
    this.reference,
    this.thread,
    this.sourceAssetId,
    this.sourceRegion,
    this.sourceObservationId,
    this.recordedBy,
    this.recordedByOtherOrganization = false,
    this.confirmedByOtherOrganization = false,
    this.confirmation,
    this.supersedesId,
    this.supersededById,
    this.notes,
  });

  final String id;
  final String jobId;
  final String dimension;
  final String component;
  final String? valueText;
  final String? valueMin;
  final String? valueMax;
  final String? unit;
  final String? normalizedMinMm;
  final String? normalizedMaxMm;
  final String? resolutionMm;
  final String? precision;
  final String method;
  final String? tool;
  final String? reference;
  final ThreadParts? thread;
  final String? sourceAssetId;
  final Map<String, dynamic>? sourceRegion;
  final String? sourceObservationId;
  final String state;
  final Provenance provenance;
  final String? recordedBy;

  /// Another contractor organisation RECORDED this (the recorder and their notes are
  /// withheld; the value stays as evidence). Judged separately from the confirmer.
  final bool recordedByOtherOrganization;

  /// Another contractor organisation CONFIRMED this (who confirmed is withheld). The
  /// recorder may still be the owner or the reader's own organisation.
  final bool confirmedByOtherOrganization;
  final Confirmation? confirmation;
  final String? supersedesId;
  final String? supersededById;
  final bool isCurrent;
  final int jobRevision;
  final String? notes;
  final DateTime createdAt;

  /// Recorded or confirmed by another contractor organisation (shown without names).
  bool get fromOtherOrganization =>
      recordedByOtherOrganization || provenance.otherOrganization || confirmedByOtherOrganization;

  /// Another organisation recorded it (the recorder is withheld) — from the server's
  /// recorder flags only, never inferred from the confirmer.
  bool get recordedByAnotherOrganization => recordedByOtherOrganization || provenance.otherOrganization;

  /// Another organisation confirmed it (who confirmed is withheld) — from the server's
  /// `confirmed_by_other_organization`, independent of who recorded it.
  bool get confirmedByAnotherOrganization => confirmedByOtherOrganization && confirmation?.confirmedAt != null;

  /// Value as recorded with its original unit (no invented precision).
  String get displayValue {
    final v = valueText ?? '—';
    return unit == null ? v : '$v $unit';
  }

  factory Measurement.fromJson(Map<String, dynamic> json) {
    final t = optMap(json, 'thread');
    final c = optMap(json, 'confirmation');
    return Measurement(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      dimension: req<String>(json, 'dimension'),
      component: req<String>(json, 'component'),
      valueText: opt<String>(json, 'value_text'),
      valueMin: opt<String>(json, 'value_min'),
      valueMax: opt<String>(json, 'value_max'),
      unit: opt<String>(json, 'unit'),
      normalizedMinMm: opt<String>(json, 'normalized_min_mm'),
      normalizedMaxMm: opt<String>(json, 'normalized_max_mm'),
      resolutionMm: opt<String>(json, 'resolution_mm'),
      precision: opt<String>(json, 'precision'),
      method: req<String>(json, 'method'),
      tool: opt<String>(json, 'tool'),
      reference: opt<String>(json, 'reference'),
      thread: t == null ? null : ThreadParts.fromJson(t),
      sourceAssetId: opt<String>(json, 'source_asset_id'),
      sourceRegion: optMap(json, 'source_region'),
      sourceObservationId: opt<String>(json, 'source_observation_id'),
      state: req<String>(json, 'state'),
      provenance: Provenance.fromJson(reqMap(json, 'provenance')),
      recordedBy: opt<String>(json, 'recorded_by'),
      recordedByOtherOrganization: opt<bool>(json, 'recorded_by_other_organization') ?? false,
      confirmedByOtherOrganization: opt<bool>(json, 'confirmed_by_other_organization') ?? false,
      confirmation: c == null ? null : Confirmation.fromJson(c),
      supersedesId: opt<String>(json, 'supersedes_id'),
      supersededById: opt<String>(json, 'superseded_by_id'),
      isCurrent: req<bool>(json, 'is_current'),
      jobRevision: req<int>(json, 'job_revision'),
      notes: opt<String>(json, 'notes'),
      createdAt: reqDate(json, 'created_at'),
    );
  }
}

/// Input for recording or revising a measurement (`MeasurementCreate`).
class MeasurementInput {
  const MeasurementInput({
    required this.dimension,
    required this.component,
    required this.valueText,
    required this.method,
    this.unit,
    this.precision,
    this.tool,
    this.reference,
    this.notes,
    this.sourceAssetId,
  });

  final String dimension;
  final String component;
  final String valueText;
  final String? unit;
  final String? precision;
  final String method;
  final String? tool;
  final String? reference;
  final String? notes;
  final String? sourceAssetId;

  static String? _c(String? v) => v == null || v.trim().isEmpty ? null : v.trim();

  Map<String, dynamic> toJson() => {
        'dimension': dimension,
        'component': component.trim(),
        'value_text': valueText.trim(),
        if (unit != null) 'unit': unit,
        if (_c(precision) != null) 'precision': _c(precision),
        'method': method,
        if (_c(tool) != null) 'tool': _c(tool),
        if (_c(reference) != null) 'reference': _c(reference),
        if (_c(notes) != null) 'notes': _c(notes),
        if (sourceAssetId != null) 'source_asset_id': sourceAssetId,
      };
}

// ============================================================== preparation
class DimensionCheck {
  const DimensionCheck({required this.status, this.reason});

  final String status;
  final String? reason;

  factory DimensionCheck.fromJson(Map<String, dynamic> json) =>
      DimensionCheck(status: req<String>(json, 'status'), reason: opt<String>(json, 'reason'));
}

class CatalogueCandidate {
  const CatalogueCandidate({
    required this.productId,
    required this.sku,
    required this.name,
    required this.priceCents,
    required this.currency,
    required this.isActive,
    required this.inStock,
    required this.fitmentStatus,
    required this.fitmentMessage,
    required this.dimensionCheck,
    this.brand,
    this.salePriceCents,
  });

  final String productId;
  final String sku;
  final String name;
  final String? brand;
  final int priceCents;
  final int? salePriceCents;
  final String currency;
  final bool isActive;
  final bool inStock;
  final String fitmentStatus;
  final String fitmentMessage;
  final DimensionCheck dimensionCheck;

  int get effectivePriceCents => salePriceCents ?? priceCents;

  factory CatalogueCandidate.fromJson(Map<String, dynamic> json) => CatalogueCandidate(
        productId: req<String>(json, 'product_id'),
        sku: req<String>(json, 'sku'),
        name: req<String>(json, 'name'),
        brand: opt<String>(json, 'brand'),
        priceCents: req<int>(json, 'price_cents'),
        salePriceCents: opt<int>(json, 'sale_price_cents'),
        currency: req<String>(json, 'currency'),
        isActive: req<bool>(json, 'is_active'),
        inStock: req<bool>(json, 'in_stock'),
        fitmentStatus: req<String>(json, 'fitment_status'),
        fitmentMessage: req<String>(json, 'fitment_message'),
        dimensionCheck: DimensionCheck.fromJson(reqMap(json, 'dimension_check')),
      );
}

class ItemDependency {
  const ItemDependency({required this.measurementId, required this.state, this.dimension, this.valueText, this.unit});

  final String measurementId;
  final String? dimension;
  final String? valueText;
  final String? unit;
  final String state;

  factory ItemDependency.fromJson(Map<String, dynamic> json) => ItemDependency(
        measurementId: req<String>(json, 'measurement_id'),
        dimension: opt<String>(json, 'dimension'),
        valueText: opt<String>(json, 'value_text'),
        unit: opt<String>(json, 'unit'),
        state: req<String>(json, 'state'),
      );
}

class PreparationItem {
  const PreparationItem({
    required this.id,
    required this.jobId,
    required this.category,
    required this.name,
    required this.purpose,
    required this.openRequirements,
    required this.specification,
    required this.dependsOn,
    required this.supportingAssetIds,
    required this.origin,
    required this.createdByRole,
    required this.status,
    required this.requirementState,
    required this.catalogueMatch,
    required this.candidates,
    required this.evidenceChangedSinceConfirmation,
    required this.evidenceRequestIds,
    required this.jobRevision,
    required this.version,
    required this.commercialNote,
    required this.createdAt,
    required this.updatedAt,
    this.quantity,
    this.unit,
    this.quantityBasis,
    this.sourceNote,
    this.confirmedProduct,
    this.confirmedBy,
    this.confirmedByOtherOrganization = false,
    this.confirmedAt,
    this.confirmedJobRevision,
    this.replacedById,
  });

  final String id;
  final String jobId;
  final String category;
  final String name;
  final String purpose;
  final String? quantity;
  final String? unit;
  final String? quantityBasis;
  final List<String> openRequirements;
  final Map<String, dynamic> specification;
  final List<ItemDependency> dependsOn;
  final List<String> supportingAssetIds;
  final String? sourceNote;
  final String origin;
  final String createdByRole;
  final String status;
  final String requirementState;
  final String catalogueMatch;
  final List<CatalogueCandidate> candidates;
  final CatalogueCandidate? confirmedProduct;
  final String? confirmedBy;

  /// Confirmed by another contractor organisation: the server withholds who
  /// (`confirmed_by_other_organization`, with `confirmed_by` null).
  final bool confirmedByOtherOrganization;
  final DateTime? confirmedAt;
  final int? confirmedJobRevision;
  final bool evidenceChangedSinceConfirmation;
  final String? replacedById;
  final List<String> evidenceRequestIds;
  final int jobRevision;
  final int version;
  final String commercialNote;
  final DateTime createdAt;
  final DateTime updatedAt;

  bool get isActive => !const {'rejected', 'replaced', 'superseded'}.contains(status);

  /// A live item whose candidates may be bought (never a rejected, replaced or
  /// superseded one).
  bool get isLive => const {'suggested', 'needs_evidence', 'contractor_confirmed'}.contains(status);

  factory PreparationItem.fromJson(Map<String, dynamic> json) {
    final cp = optMap(json, 'confirmed_product');
    return PreparationItem(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      category: req<String>(json, 'category'),
      name: req<String>(json, 'name'),
      purpose: req<String>(json, 'purpose'),
      quantity: opt<String>(json, 'quantity'),
      unit: opt<String>(json, 'unit'),
      quantityBasis: opt<String>(json, 'quantity_basis'),
      openRequirements: stringList(json, 'open_requirements'),
      specification: reqMap(json, 'specification'),
      dependsOn: _list(json, 'depends_on', ItemDependency.fromJson),
      supportingAssetIds: stringList(json, 'supporting_asset_ids'),
      sourceNote: opt<String>(json, 'source_note'),
      origin: req<String>(json, 'origin'),
      createdByRole: req<String>(json, 'created_by_role'),
      status: req<String>(json, 'status'),
      requirementState: req<String>(json, 'requirement_state'),
      catalogueMatch: req<String>(json, 'catalogue_match'),
      candidates: _list(json, 'candidates', CatalogueCandidate.fromJson),
      confirmedProduct: cp == null ? null : CatalogueCandidate.fromJson(cp),
      confirmedBy: opt<String>(json, 'confirmed_by'),
      confirmedByOtherOrganization: opt<bool>(json, 'confirmed_by_other_organization') ?? false,
      confirmedAt: _optDate(json, 'confirmed_at'),
      confirmedJobRevision: opt<int>(json, 'confirmed_job_revision'),
      evidenceChangedSinceConfirmation: req<bool>(json, 'evidence_changed_since_confirmation'),
      replacedById: opt<String>(json, 'replaced_by_id'),
      evidenceRequestIds: stringList(json, 'evidence_request_ids'),
      jobRevision: req<int>(json, 'job_revision'),
      version: req<int>(json, 'version'),
      commercialNote: req<String>(json, 'commercial_note'),
      createdAt: reqDate(json, 'created_at'),
      updatedAt: reqDate(json, 'updated_at'),
    );
  }
}

/// Input for adding or replacing a preparation item (`PreparationItemCreate`).
class PreparationItemInput {
  const PreparationItemInput({
    required this.category,
    required this.name,
    required this.purpose,
    this.quantity,
    this.unit,
    this.quantityBasis,
    this.openRequirements = const [],
    this.sourceNote,
  });

  final String category;
  final String name;
  final String purpose;

  /// Decimal as text (e.g. "2", "0.8"); never a float.
  final String? quantity;
  final String? unit;
  final String? quantityBasis;
  final List<String> openRequirements;
  final String? sourceNote;

  static String? _c(String? v) => v == null || v.trim().isEmpty ? null : v.trim();

  Map<String, dynamic> toJson() => {
        'category': category,
        'name': name.trim(),
        'purpose': purpose.trim(),
        if (_c(quantity) != null) 'quantity': _c(quantity),
        if (_c(unit) != null) 'unit': _c(unit),
        if (_c(quantityBasis) != null) 'quantity_basis': _c(quantityBasis),
        'open_requirements': [for (final r in openRequirements) if (r.trim().isNotEmpty) r.trim()],
        if (_c(sourceNote) != null) 'source_note': _c(sourceNote),
      };
}

class EvidenceRequestRef {
  const EvidenceRequestRef({
    required this.id,
    required this.category,
    required this.prompt,
    required this.reason,
    required this.requesterRole,
    required this.status,
    required this.priority,
  });

  final String id;
  final String category;
  final String prompt;
  final String reason;
  final String requesterRole;
  final String status;
  final String priority;

  factory EvidenceRequestRef.fromJson(Map<String, dynamic> json) => EvidenceRequestRef(
        id: req<String>(json, 'id'),
        category: req<String>(json, 'category'),
        prompt: req<String>(json, 'prompt'),
        reason: req<String>(json, 'reason'),
        requesterRole: req<String>(json, 'requester_role'),
        status: req<String>(json, 'status'),
        priority: req<String>(json, 'priority'),
      );
}

class ItemEvidenceResult {
  const ItemEvidenceResult({required this.item, required this.evidenceRequest});

  final PreparationItem item;
  final EvidenceRequestRef evidenceRequest;

  factory ItemEvidenceResult.fromJson(Map<String, dynamic> json) => ItemEvidenceResult(
        item: PreparationItem.fromJson(reqMap(json, 'item')),
        evidenceRequest: EvidenceRequestRef.fromJson(reqMap(json, 'evidence_request')),
      );
}

// ============================================================== briefs
class BriefAcknowledgement {
  const BriefAcknowledgement({
    required this.id,
    required this.kind,
    required this.userId,
    required this.organizationId,
    required this.createdAt,
    this.note,
  });

  final String id;
  final String kind;
  final String? note;
  final String userId;
  final String organizationId;
  final DateTime createdAt;

  factory BriefAcknowledgement.fromJson(Map<String, dynamic> json) => BriefAcknowledgement(
        id: req<String>(json, 'id'),
        kind: req<String>(json, 'kind'),
        note: opt<String>(json, 'note'),
        userId: req<String>(json, 'user_id'),
        organizationId: req<String>(json, 'organization_id'),
        createdAt: reqDate(json, 'created_at'),
      );
}

class Brief {
  const Brief({
    required this.id,
    required this.jobId,
    required this.revisionNumber,
    required this.status,
    required this.sections,
    required this.jobRevision,
    required this.currentJobRevision,
    required this.contentDigest,
    required this.createdBy,
    required this.createdAt,
    required this.isCurrent,
    required this.outdated,
    required this.outdatedReasons,
    required this.acknowledgements,
    this.recipient,
    this.content,
    this.publishedAt,
  });

  final String id;
  final String jobId;
  final int revisionNumber;
  final String status;
  final List<String> sections;
  final Map<String, dynamic>? recipient;
  final Map<String, dynamic>? content;
  final int jobRevision;
  final int currentJobRevision;
  final String contentDigest;
  final String createdBy;
  final DateTime createdAt;
  final DateTime? publishedAt;
  final bool isCurrent;
  final bool outdated;
  final List<String> outdatedReasons;
  final List<BriefAcknowledgement> acknowledgements;

  bool get isPublished => status == 'published';
  bool get isPreview => status == 'preview';

  String? get recipientName => recipient?['organization_name'] as String?;

  factory Brief.fromJson(Map<String, dynamic> json) => Brief(
        id: req<String>(json, 'id'),
        jobId: req<String>(json, 'job_id'),
        revisionNumber: req<int>(json, 'revision_number'),
        status: req<String>(json, 'status'),
        sections: stringList(json, 'sections'),
        recipient: optMap(json, 'recipient'),
        content: optMap(json, 'content'),
        jobRevision: req<int>(json, 'job_revision'),
        currentJobRevision: req<int>(json, 'current_job_revision'),
        contentDigest: req<String>(json, 'content_digest'),
        createdBy: req<String>(json, 'created_by'),
        createdAt: reqDate(json, 'created_at'),
        publishedAt: _optDate(json, 'published_at'),
        isCurrent: req<bool>(json, 'is_current'),
        outdated: req<bool>(json, 'outdated'),
        outdatedReasons: stringList(json, 'outdated_reasons'),
        acknowledgements: _list(json, 'acknowledgements', BriefAcknowledgement.fromJson),
      );
}

class BriefAckResult {
  const BriefAckResult({required this.acknowledgement, this.evidenceRequest});

  final BriefAcknowledgement acknowledgement;
  final EvidenceRequestRef? evidenceRequest;

  factory BriefAckResult.fromJson(Map<String, dynamic> json) {
    final r = optMap(json, 'evidence_request');
    return BriefAckResult(
      acknowledgement: BriefAcknowledgement.fromJson(reqMap(json, 'acknowledgement')),
      evidenceRequest: r == null ? null : EvidenceRequestRef.fromJson(r),
    );
  }
}

// ============================================================== scope
class EstimateLine {
  const EstimateLine({
    required this.description,
    required this.kind,
    required this.amountMinor,
    this.quantity,
    this.unit,
    this.unitPriceMinor,
  });

  final String description;
  final String kind;
  final String? quantity;
  final String? unit;
  final int? unitPriceMinor;
  final int amountMinor;

  factory EstimateLine.fromJson(Map<String, dynamic> json) => EstimateLine(
        description: req<String>(json, 'description'),
        kind: req<String>(json, 'kind'),
        quantity: opt<String>(json, 'quantity'),
        unit: opt<String>(json, 'unit'),
        unitPriceMinor: opt<int>(json, 'unit_price_minor'),
        amountMinor: req<int>(json, 'amount_minor'),
      );
}

class ScopeDecision {
  const ScopeDecision({
    required this.id,
    required this.scopeRevisionId,
    required this.decision,
    required this.revisionDigest,
    required this.decidedBy,
    required this.decidedAt,
    this.note,
  });

  final String id;
  final String scopeRevisionId;
  final String decision;
  final String revisionDigest;
  final String decidedBy;
  final String? note;
  final DateTime decidedAt;

  factory ScopeDecision.fromJson(Map<String, dynamic> json) => ScopeDecision(
        id: req<String>(json, 'id'),
        scopeRevisionId: req<String>(json, 'scope_revision_id'),
        decision: req<String>(json, 'decision'),
        revisionDigest: req<String>(json, 'revision_digest'),
        decidedBy: req<String>(json, 'decided_by'),
        note: opt<String>(json, 'note'),
        decidedAt: reqDate(json, 'decided_at'),
      );
}

class ScopeRevision {
  const ScopeRevision({
    required this.id,
    required this.jobId,
    required this.revisionNumber,
    required this.isChange,
    required this.proposedBy,
    required this.summary,
    required this.tasks,
    required this.estimateLines,
    required this.status,
    required this.contentDigest,
    required this.isCurrent,
    required this.createdAt,
    this.supersedesId,
    this.organizationId,
    this.estimateTotalMinor,
    this.currency,
    this.exclusions,
    this.assumptions,
    this.decision,
  });

  final String id;
  final String jobId;
  final int revisionNumber;
  final bool isChange;
  final String? supersedesId;
  final String proposedBy;
  final String? organizationId;
  final String summary;
  final List<Map<String, dynamic>> tasks;
  final List<EstimateLine> estimateLines;
  final int? estimateTotalMinor;
  final String? currency;
  final String? exclusions;
  final String? assumptions;
  final String status;
  final String contentDigest;
  final bool isCurrent;
  final ScopeDecision? decision;
  final DateTime createdAt;

  /// Open for an owner decision.
  bool get isOpen => decision == null && (status == 'proposed' || status == 'draft');

  factory ScopeRevision.fromJson(Map<String, dynamic> json) {
    final d = optMap(json, 'decision');
    return ScopeRevision(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      revisionNumber: req<int>(json, 'revision_number'),
      isChange: req<bool>(json, 'is_change'),
      supersedesId: opt<String>(json, 'supersedes_id'),
      proposedBy: req<String>(json, 'proposed_by'),
      organizationId: opt<String>(json, 'organization_id'),
      summary: req<String>(json, 'summary'),
      tasks: mapList(json, 'tasks'),
      estimateLines: _list(json, 'estimate_lines', EstimateLine.fromJson),
      estimateTotalMinor: opt<int>(json, 'estimate_total_minor'),
      currency: opt<String>(json, 'currency'),
      exclusions: opt<String>(json, 'exclusions'),
      assumptions: opt<String>(json, 'assumptions'),
      status: req<String>(json, 'status'),
      contentDigest: req<String>(json, 'content_digest'),
      isCurrent: req<bool>(json, 'is_current'),
      decision: d == null ? null : ScopeDecision.fromJson(d),
      createdAt: reqDate(json, 'created_at'),
    );
  }
}

/// One estimate line as entered by the contractor (integer minor units).
class EstimateLineInput {
  const EstimateLineInput({
    required this.description,
    required this.kind,
    this.quantity,
    this.unit,
    this.unitPriceMinor,
    this.amountMinor,
  });

  final String description;
  final String kind;
  final String? quantity;
  final String? unit;
  final int? unitPriceMinor;
  final int? amountMinor;

  Map<String, dynamic> toJson() => {
        'description': description.trim(),
        'kind': kind,
        if (quantity != null && quantity!.trim().isNotEmpty) 'quantity': quantity!.trim(),
        if (unit != null && unit!.trim().isNotEmpty) 'unit': unit!.trim(),
        if (unitPriceMinor != null) 'unit_price_minor': unitPriceMinor,
        if (amountMinor != null) 'amount_minor': amountMinor,
      };
}

class ScopeInput {
  const ScopeInput({
    required this.summary,
    this.tasks = const [],
    this.estimateLines = const [],
    this.currency,
    this.exclusions,
    this.assumptions,
    this.supersedesId,
  });

  final String summary;
  final List<({String description, bool needsSiteInspection})> tasks;
  final List<EstimateLineInput> estimateLines;
  final String? currency;
  final String? exclusions;
  final String? assumptions;
  final String? supersedesId;

  Map<String, dynamic> toJson() => {
        'summary': summary.trim(),
        'tasks': [
          for (final t in tasks)
            {'description': t.description.trim(), 'needs_site_inspection': t.needsSiteInspection},
        ],
        'estimate_lines': [for (final l in estimateLines) l.toJson()],
        if (currency != null) 'currency': currency,
        if (exclusions != null && exclusions!.trim().isNotEmpty) 'exclusions': exclusions!.trim(),
        if (assumptions != null && assumptions!.trim().isNotEmpty) 'assumptions': assumptions!.trim(),
        if (supersedesId != null) 'supersedes_id': supersedesId,
      };
}

// ============================================================== visits
class VisitEvent {
  const VisitEvent({
    required this.id,
    required this.jobId,
    required this.kind,
    required this.actorRole,
    required this.occurredAt,
    required this.recordedAt,
    required this.contested,
    this.assignmentId,
    this.actorId,
    this.actorName,
    this.note,
    this.contestsEventId,
  });

  final String id;
  final String jobId;
  final String? assignmentId;
  final String kind;
  final String? actorId;
  final String? actorName;
  final String actorRole;
  final DateTime occurredAt;
  final DateTime recordedAt;
  final String? note;
  final String? contestsEventId;
  final bool contested;

  factory VisitEvent.fromJson(Map<String, dynamic> json) => VisitEvent(
        id: req<String>(json, 'id'),
        jobId: req<String>(json, 'job_id'),
        assignmentId: opt<String>(json, 'assignment_id'),
        kind: req<String>(json, 'kind'),
        actorId: opt<String>(json, 'actor_id'),
        actorName: opt<String>(json, 'actor_name'),
        actorRole: req<String>(json, 'actor_role'),
        occurredAt: reqDate(json, 'occurred_at'),
        recordedAt: reqDate(json, 'recorded_at'),
        note: opt<String>(json, 'note'),
        contestsEventId: opt<String>(json, 'contests_event_id'),
        contested: req<bool>(json, 'contested'),
      );
}

class VisitResult {
  const VisitResult({
    required this.event,
    required this.jobStatus,
    required this.jobVersion,
    required this.jobDisputed,
    required this.feedbackWindowOpened,
    required this.created,
  });

  final VisitEvent event;
  final String jobStatus;
  final int jobVersion;
  final bool jobDisputed;
  final bool feedbackWindowOpened;
  final bool created;

  factory VisitResult.fromJson(Map<String, dynamic> json) => VisitResult(
        event: VisitEvent.fromJson(reqMap(json, 'event')),
        jobStatus: req<String>(json, 'job_status'),
        jobVersion: req<int>(json, 'job_version'),
        jobDisputed: req<bool>(json, 'job_disputed'),
        feedbackWindowOpened: req<bool>(json, 'feedback_window_opened'),
        created: req<bool>(json, 'created'),
      );
}

class ContestResult {
  const ContestResult({
    required this.event,
    required this.jobStatus,
    required this.jobDisputed,
    required this.created,
    this.caseId,
  });

  final VisitEvent event;
  final String? caseId;
  final String jobStatus;
  final bool jobDisputed;
  final bool created;

  factory ContestResult.fromJson(Map<String, dynamic> json) => ContestResult(
        event: VisitEvent.fromJson(reqMap(json, 'event')),
        caseId: opt<String>(json, 'case_id'),
        jobStatus: req<String>(json, 'job_status'),
        jobDisputed: req<bool>(json, 'job_disputed'),
        created: req<bool>(json, 'created'),
      );
}

// ============================================================== feedback
class PersonRef {
  const PersonRef({required this.id, required this.role, this.name});

  final String id;
  final String? name;
  final String role;

  factory PersonRef.fromJson(Map<String, dynamic> json) =>
      PersonRef(id: req<String>(json, 'id'), name: opt<String>(json, 'name'), role: req<String>(json, 'role'));
}

class FeedbackReply {
  const FeedbackReply({
    required this.id,
    required this.kind,
    required this.author,
    required this.contentState,
    required this.createdAt,
    this.text,
  });

  final String id;
  final String kind;
  final PersonRef author;
  final String? text;
  final String contentState;
  final DateTime createdAt;

  factory FeedbackReply.fromJson(Map<String, dynamic> json) => FeedbackReply(
        id: req<String>(json, 'id'),
        kind: req<String>(json, 'kind'),
        author: PersonRef.fromJson(reqMap(json, 'author')),
        text: opt<String>(json, 'text'),
        contentState: req<String>(json, 'content_state'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// A rating: 1–5, `not_applicable`, or absent (never zero).
typedef Rating = Object; // int | 'not_applicable'

class Review {
  const Review({
    required this.id,
    required this.jobId,
    required this.direction,
    required this.status,
    required this.version,
    required this.author,
    required this.organizationId,
    required this.basis,
    required this.ratings,
    required this.contentState,
    required this.createdAt,
    required this.updatedAt,
    required this.responses,
    this.organizationName,
    this.visitDate,
    this.narrative,
    this.submittedAt,
    this.revealedAt,
  });

  final String id;
  final String jobId;
  final String direction;
  final String status;
  final int version;
  final PersonRef author;
  final String organizationId;
  final String? organizationName;
  final String basis;
  final DateTime? visitDate;
  final Map<String, Rating> ratings;
  final String? narrative;
  final String contentState;
  final DateTime? submittedAt;
  final DateTime? revealedAt;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<FeedbackReply> responses;

  bool get isDraft => status == 'draft';
  bool get isRevealed => revealedAt != null || status == 'revealed';

  factory Review.fromJson(Map<String, dynamic> json) {
    final org = reqMap(json, 'organization');
    final ratings = <String, Rating>{};
    for (final e in reqMap(json, 'ratings').entries) {
      final v = e.value;
      if (v is int || v == 'not_applicable') {
        ratings[e.key] = v as Object;
      } else {
        throw FormatException('Field "ratings.${e.key}": expected 1–5 or not_applicable, got $v');
      }
    }
    return Review(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      direction: req<String>(json, 'direction'),
      status: req<String>(json, 'status'),
      version: req<int>(json, 'version'),
      author: PersonRef.fromJson(reqMap(json, 'author')),
      organizationId: req<String>(org, 'id'),
      organizationName: opt<String>(org, 'name'),
      basis: req<String>(json, 'basis'),
      visitDate: _optDate(json, 'visit_date'),
      ratings: ratings,
      narrative: opt<String>(json, 'narrative'),
      contentState: req<String>(json, 'content_state'),
      submittedAt: _optDate(json, 'submitted_at'),
      revealedAt: _optDate(json, 'revealed_at'),
      createdAt: reqDate(json, 'created_at'),
      updatedAt: reqDate(json, 'updated_at'),
      responses: _list(json, 'responses', FeedbackReply.fromJson),
    );
  }
}

class FeedbackWindow {
  const FeedbackWindow({
    required this.basis,
    required this.opensAt,
    required this.closesAt,
    required this.isOpen,
    required this.revealed,
    this.revealedAt,
  });

  final String basis;
  final DateTime opensAt;
  final DateTime closesAt;
  final bool isOpen;
  final bool revealed;
  final DateTime? revealedAt;

  factory FeedbackWindow.fromJson(Map<String, dynamic> json) => FeedbackWindow(
        basis: req<String>(json, 'basis'),
        opensAt: reqDate(json, 'opens_at'),
        closesAt: reqDate(json, 'closes_at'),
        isOpen: req<bool>(json, 'is_open'),
        revealed: req<bool>(json, 'revealed'),
        revealedAt: _optDate(json, 'revealed_at'),
      );
}

class FeedbackDimension {
  const FeedbackDimension({required this.key, required this.label});

  final String key;
  final String label;

  factory FeedbackDimension.fromJson(Map<String, dynamic> json) =>
      FeedbackDimension(key: req<String>(json, 'key'), label: req<String>(json, 'label'));
}

class FeedbackOverview {
  const FeedbackOverview({
    required this.jobId,
    required this.mySide,
    required this.myDirection,
    required this.eligible,
    required this.revealRule,
    required this.dimensions,
    required this.canEdit,
    this.ineligibleReason,
    this.window,
    this.mine,
    this.theirs,
  });

  final String jobId;
  final String mySide;
  final String myDirection;
  final bool eligible;
  final String? ineligibleReason;
  final FeedbackWindow? window;
  final String revealRule;
  final List<FeedbackDimension> dimensions;
  final bool canEdit;
  final Review? mine;
  final Review? theirs;

  factory FeedbackOverview.fromJson(Map<String, dynamic> json) {
    final w = optMap(json, 'window');
    final m = optMap(json, 'mine');
    final t = optMap(json, 'theirs');
    return FeedbackOverview(
      jobId: req<String>(json, 'job_id'),
      mySide: req<String>(json, 'my_side'),
      myDirection: req<String>(json, 'my_direction'),
      eligible: req<bool>(json, 'eligible'),
      ineligibleReason: opt<String>(json, 'ineligible_reason'),
      window: w == null ? null : FeedbackWindow.fromJson(w),
      revealRule: req<String>(json, 'reveal_rule'),
      dimensions: _list(json, 'dimensions', FeedbackDimension.fromJson),
      canEdit: req<bool>(json, 'can_edit'),
      mine: m == null ? null : Review.fromJson(m),
      theirs: t == null ? null : Review.fromJson(t),
    );
  }
}

class FeedbackReport {
  const FeedbackReport({
    required this.id,
    required this.category,
    required this.status,
    required this.restrictContent,
    required this.createdAt,
    this.feedbackId,
  });

  final String id;
  final String? feedbackId;
  final String category;
  final String status;
  final bool restrictContent;
  final DateTime createdAt;

  factory FeedbackReport.fromJson(Map<String, dynamic> json) => FeedbackReport(
        id: req<String>(json, 'id'),
        feedbackId: opt<String>(json, 'feedback_id'),
        category: req<String>(json, 'category'),
        status: req<String>(json, 'status'),
        restrictContent: req<bool>(json, 'restrict_content'),
        createdAt: reqDate(json, 'created_at'),
      );
}
