import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/contractors/data/contractors_api.dart';

/// My contractor-organization memberships (empty for most people).
final myMembershipsProvider = FutureProvider.autoDispose<List<MyMembership>>((ref) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).myMemberships();
});

/// Assigned jobs plus pending invitations for organizations I administer.
final contractorInboxProvider = FutureProvider.autoDispose<ContractorInbox>((ref) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).inbox();
});

final orgInvitationsProvider = FutureProvider.autoDispose.family<List<InvitationSummary>, String>((ref, orgId) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).orgInvitations(orgId);
});

final orgMembersProvider = FutureProvider.autoDispose.family<List<OrgMember>, String>((ref, orgId) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).orgMembers(orgId);
});

/// Directory search (owner sharing). A listing grants no access.
final directoryProvider = FutureProvider.autoDispose.family<List<DirectoryEntry>, String>((ref, query) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).directory(query: query);
});
