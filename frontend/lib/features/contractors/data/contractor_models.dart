/// Contractor organizations, memberships and the assigned-job inbox
/// (`/contractors/*`, `backend/app/schemas/service_jobs.py`).
library;

import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';

DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

/// A directory row an owner can invite. Being listed grants no access.
class DirectoryEntry {
  const DirectoryEntry({required this.id, required this.name, this.tradingName});

  final String id;
  final String name;
  final String? tradingName;

  String get displayName =>
      tradingName == null || tradingName!.isEmpty || tradingName == name ? name : '$name ($tradingName)';

  factory DirectoryEntry.fromJson(Map<String, dynamic> json) => DirectoryEntry(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        tradingName: opt<String>(json, 'trading_name'),
      );
}

class MyMembership {
  const MyMembership({required this.organizationId, required this.name, required this.role, this.tradingName, this.verifiedAt});

  final String organizationId;
  final String name;
  final String? tradingName;
  final String role;
  final DateTime? verifiedAt;

  bool get isAdmin => role == 'admin';

  factory MyMembership.fromJson(Map<String, dynamic> json) => MyMembership(
        organizationId: req<String>(json, 'organization_id'),
        name: req<String>(json, 'name'),
        tradingName: opt<String>(json, 'trading_name'),
        role: req<String>(json, 'role'),
        verifiedAt: _optDate(json, 'verified_at'),
      );
}

class OrgMember {
  const OrgMember({required this.userId, required this.role, required this.status, this.name, this.email, this.verifiedAt, this.removedAt});

  final String userId;
  final String? name;
  final String? email;
  final String role;
  final String status;
  final DateTime? verifiedAt;
  final DateTime? removedAt;

  String get displayName => name ?? email ?? 'Member';

  factory OrgMember.fromJson(Map<String, dynamic> json) => OrgMember(
        userId: req<String>(json, 'user_id'),
        name: opt<String>(json, 'name'),
        email: opt<String>(json, 'email'),
        role: req<String>(json, 'role'),
        status: req<String>(json, 'status'),
        verifiedAt: _optDate(json, 'verified_at'),
        removedAt: _optDate(json, 'removed_at'),
      );
}

/// What an organization administrator sees of an invitation: no evidence, no access.
class InvitationSummary {
  const InvitationSummary({
    required this.assignmentId,
    required this.jobId,
    required this.organizationId,
    required this.status,
    required this.jobTitle,
    required this.sections,
    required this.liveUpdates,
    required this.invitedAt,
    required this.version,
    required this.members,
    this.vesselMake,
    this.vesselModel,
    this.inviterFirstName,
    this.acceptedAt,
  });

  final String assignmentId;
  final String jobId;
  final String organizationId;
  final String status;
  final String jobTitle;
  final String? vesselMake;
  final String? vesselModel;
  final List<String> sections;
  final bool liveUpdates;
  final String? inviterFirstName;
  final DateTime invitedAt;
  final DateTime? acceptedAt;
  final int version;
  final List<AssignmentMember> members;

  bool get isPending => status == 'invited';

  String get vesselLine => [vesselMake, vesselModel].whereType<String>().join(' ');

  factory InvitationSummary.fromJson(Map<String, dynamic> json) => InvitationSummary(
        assignmentId: req<String>(json, 'assignment_id'),
        jobId: req<String>(json, 'job_id'),
        organizationId: req<String>(json, 'organization_id'),
        status: req<String>(json, 'status'),
        jobTitle: req<String>(json, 'job_title'),
        vesselMake: opt<String>(json, 'vessel_make'),
        vesselModel: opt<String>(json, 'vessel_model'),
        sections: stringList(json, 'sections'),
        liveUpdates: req<bool>(json, 'live_updates'),
        inviterFirstName: opt<String>(json, 'inviter_first_name'),
        invitedAt: reqDate(json, 'invited_at'),
        acceptedAt: _optDate(json, 'accepted_at'),
        version: req<int>(json, 'version'),
        members: [for (final m in mapList(json, 'members')) AssignmentMember.fromJson(m)],
      );
}

class InboxJob {
  const InboxJob({
    required this.jobId,
    required this.title,
    required this.status,
    required this.assignmentId,
    required this.organizationId,
    required this.organizationName,
    required this.sections,
    required this.restrictedAccess,
    required this.updatedAt,
    this.acceptedAt,
  });

  final String jobId;
  final String title;
  final String status;
  final String assignmentId;
  final String organizationId;
  final String organizationName;
  final List<String> sections;
  final bool restrictedAccess;
  final DateTime? acceptedAt;
  final DateTime updatedAt;

  factory InboxJob.fromJson(Map<String, dynamic> json) => InboxJob(
        jobId: req<String>(json, 'job_id'),
        title: req<String>(json, 'title'),
        status: req<String>(json, 'status'),
        assignmentId: req<String>(json, 'assignment_id'),
        organizationId: req<String>(json, 'organization_id'),
        organizationName: req<String>(json, 'organization_name'),
        sections: stringList(json, 'sections'),
        restrictedAccess: req<bool>(json, 'restricted_access'),
        acceptedAt: _optDate(json, 'accepted_at'),
        updatedAt: reqDate(json, 'updated_at'),
      );
}

class ContractorInbox {
  const ContractorInbox({required this.assigned, required this.invitations});

  final List<InboxJob> assigned;
  final List<InvitationSummary> invitations;

  bool get isEmpty => assigned.isEmpty && invitations.isEmpty;

  factory ContractorInbox.fromJson(Map<String, dynamic> json) => ContractorInbox(
        assigned: [for (final m in mapList(json, 'assigned')) InboxJob.fromJson(m)],
        invitations: [for (final m in mapList(json, 'invitations')) InvitationSummary.fromJson(m)],
      );
}
