// Typed models for the case-scoped moderation console (`/moderation/cases`).
import 'package:helm_marine/core/models/json.dart';

/// Roles that may open the moderation console (server-held; read from /auth/me).
const moderatorRoles = {'moderator', 'admin'};

const caseCategoryLabels = <String, String>{
  'factual_dispute': 'Factual dispute',
  'opinion': 'Opinion',
  'harassment': 'Harassment',
  'personal_or_security_information': 'Personal or security information',
  'other': 'Other',
  'visit_contested': 'Contested visit record',
};

const caseStatusLabels = <String, String>{
  'open': 'Open',
  'under_review': 'Under review',
  'resolved': 'Resolved',
};

const dispositionLabels = <String, String>{
  'no_action': 'No action needed',
  'addendum_requested': 'Addendum requested from the author',
  'content_restricted': 'Content restricted',
  'content_removed_for_personal_information': 'Content removed (personal or security information)',
  'eligibility_corrected': 'Feedback eligibility corrected',
};

const actionLabels = <String, String>{
  'assign': 'Assign to me',
  'restrict': 'Restrict the content while investigating',
  'unrestrict': 'Lift the restriction',
  'resolve': 'Resolve with a disposition',
};

String _label(Map<String, String> labels, String value) => labels[value] ?? value.replaceAll('_', ' ');

String caseCategoryLabel(String v) => _label(caseCategoryLabels, v);
String caseStatusLabel(String v) => _label(caseStatusLabels, v);
String dispositionLabel(String v) => _label(dispositionLabels, v);

String auditActionLabel(String action) {
  if (action.startsWith('resolve:')) return 'Resolved — ${dispositionLabel(action.substring(8))}';
  return switch (action) {
    'reported' => 'Reported',
    'assign' => 'Assigned',
    'restrict' => 'Content restricted',
    'unrestrict' => 'Restriction lifted',
    'contested' => 'Visit record contested',
    _ => action.replaceAll('_', ' '),
  };
}

class CaseSummary {
  const CaseSummary({
    required this.id,
    required this.jobId,
    required this.feedbackId,
    required this.visitEventId,
    required this.category,
    required this.status,
    required this.restrictContent,
    required this.assignedModeratorId,
    required this.contentVersion,
    required this.disposition,
    required this.retentionHold,
    required this.createdAt,
    required this.resolvedAt,
  });

  final String id;
  final String jobId;
  final String? feedbackId;
  final String? visitEventId;
  final String category;

  /// open | under_review | resolved
  final String status;
  final bool restrictContent;
  final String? assignedModeratorId;
  final int? contentVersion;
  final String? disposition;
  final bool retentionHold;
  final DateTime createdAt;
  final DateTime? resolvedAt;

  bool get resolved => status == 'resolved';
  String get subject => feedbackId != null ? 'Reported review' : 'Contested visit record';

  factory CaseSummary.fromJson(Map<String, dynamic> json) {
    final resolved = opt<String>(json, 'resolved_at');
    return CaseSummary(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      feedbackId: opt<String>(json, 'feedback_id'),
      visitEventId: opt<String>(json, 'visit_event_id'),
      category: req<String>(json, 'category'),
      status: req<String>(json, 'status'),
      restrictContent: req<bool>(json, 'restrict_content'),
      assignedModeratorId: opt<String>(json, 'assigned_moderator_id'),
      contentVersion: opt<int>(json, 'content_version'),
      disposition: opt<String>(json, 'disposition'),
      retentionHold: req<bool>(json, 'retention_hold'),
      createdAt: reqDate(json, 'created_at'),
      resolvedAt: resolved == null ? null : DateTime.parse(resolved),
    );
  }
}

class CaseJob {
  const CaseJob({required this.title, required this.status, required this.disputed, required this.organizationName});

  final String title;
  final String status;
  final bool disputed;
  final String? organizationName;

  factory CaseJob.fromJson(Map<String, dynamic> json) => CaseJob(
        title: req<String>(json, 'title'),
        status: req<String>(json, 'status'),
        disputed: req<bool>(json, 'disputed'),
        organizationName: opt<String>(json, 'organization_name'),
      );
}

/// Ratings are 1–5 or "not_applicable" (never zero).
Map<String, String> _ratings(Map<String, dynamic>? json) => {
      for (final e in (json ?? const <String, dynamic>{}).entries)
        e.key: e.value == 'not_applicable' ? 'Not applicable' : '${e.value} of 5',
    };

String ratingLabel(String key) => key.replaceAll('_', ' ').replaceFirstMapped(RegExp('^.'), (m) => m[0]!.toUpperCase());

class ReportedContent {
  const ReportedContent({required this.version, required this.ratings, required this.narrative});

  final int version;
  final Map<String, String> ratings;
  final String? narrative;

  factory ReportedContent.fromJson(Map<String, dynamic> json) => ReportedContent(
        version: req<int>(json, 'version'),
        ratings: _ratings(optMap(json, 'ratings')),
        narrative: opt<String>(json, 'narrative'),
      );
}

class CaseFeedback {
  const CaseFeedback({
    required this.direction,
    required this.status,
    required this.authorName,
    required this.authorRole,
    required this.organizationName,
    required this.contentState,
    required this.ratings,
    required this.narrative,
    required this.responses,
  });

  final String direction;
  final String status;
  final String? authorName;
  final String authorRole;
  final String? organizationName;

  /// visible | under_review | restricted | removed
  final String contentState;
  final Map<String, String> ratings;
  final String? narrative;
  final List<(String kind, String? text, String contentState)> responses;

  String get directionLabel =>
      direction == 'owner_to_contractor' ? 'Owner’s review of the contractor' : 'Contractor’s review of the owner';

  factory CaseFeedback.fromJson(Map<String, dynamic> json) {
    final author = reqMap(json, 'author');
    final org = optMap(json, 'organization');
    return CaseFeedback(
      direction: req<String>(json, 'direction'),
      status: req<String>(json, 'status'),
      authorName: opt<String>(author, 'name'),
      authorRole: req<String>(author, 'role'),
      organizationName: org == null ? null : opt<String>(org, 'name'),
      contentState: req<String>(json, 'content_state'),
      ratings: _ratings(optMap(json, 'ratings')),
      narrative: opt<String>(json, 'narrative'),
      responses: [
        for (final r in mapList(json, 'responses'))
          (req<String>(r, 'kind'), opt<String>(r, 'text'), req<String>(r, 'content_state')),
      ],
    );
  }
}

class CaseVisit {
  const CaseVisit({required this.kind, required this.actorName, required this.actorRole, required this.occurredAt, this.note});

  final String kind;
  final String? actorName;
  final String actorRole;
  final DateTime occurredAt;
  final String? note;

  factory CaseVisit.fromJson(Map<String, dynamic> json) => CaseVisit(
        kind: req<String>(json, 'kind'),
        actorName: opt<String>(json, 'actor_name'),
        actorRole: req<String>(json, 'actor_role'),
        occurredAt: reqDate(json, 'occurred_at'),
        note: opt<String>(json, 'note'),
      );
}

class CaseAction {
  const CaseAction({
    required this.id,
    required this.action,
    required this.actorId,
    required this.reason,
    required this.contentVersion,
    required this.createdAt,
  });

  final String id;
  final String action;
  final String actorId;
  final String reason;
  final int? contentVersion;
  final DateTime createdAt;

  factory CaseAction.fromJson(Map<String, dynamic> json) => CaseAction(
        id: req<String>(json, 'id'),
        action: req<String>(json, 'action'),
        actorId: req<String>(json, 'actor_id'),
        reason: req<String>(json, 'reason'),
        contentVersion: opt<int>(json, 'content_version'),
        createdAt: reqDate(json, 'created_at'),
      );
}

class CaseDetail {
  const CaseDetail({
    required this.summary,
    required this.reason,
    required this.dispositionNote,
    required this.reporterName,
    required this.job,
    required this.feedback,
    required this.reportedContent,
    required this.visitEvent,
    required this.contestEvent,
    required this.actions,
  });

  final CaseSummary summary;
  final String reason;
  final String? dispositionNote;
  final String? reporterName;
  final CaseJob job;
  final CaseFeedback? feedback;
  final ReportedContent? reportedContent;
  final CaseVisit? visitEvent;
  final CaseVisit? contestEvent;
  final List<CaseAction> actions;

  factory CaseDetail.fromJson(Map<String, dynamic> json) {
    final fb = optMap(json, 'feedback');
    final rc = optMap(json, 'reported_content');
    final ve = optMap(json, 'visit_event');
    final ce = optMap(json, 'contest_event');
    return CaseDetail(
      summary: CaseSummary.fromJson(json),
      reason: req<String>(json, 'reason'),
      dispositionNote: opt<String>(json, 'disposition_note'),
      reporterName: opt<String>(reqMap(json, 'reporter'), 'name'),
      job: CaseJob.fromJson(reqMap(json, 'job')),
      feedback: fb == null ? null : CaseFeedback.fromJson(fb),
      reportedContent: rc == null ? null : ReportedContent.fromJson(rc),
      visitEvent: ve == null ? null : CaseVisit.fromJson(ve),
      contestEvent: ce == null ? null : CaseVisit.fromJson(ce),
      actions: [for (final a in mapList(json, 'actions')) CaseAction.fromJson(a)],
    );
  }
}
