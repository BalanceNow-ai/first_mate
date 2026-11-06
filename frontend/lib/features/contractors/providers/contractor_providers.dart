import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/contractors/data/contractors_api.dart';

/// My contractor-organization memberships (empty for most people).
final myMembershipsProvider = FutureProvider.autoDispose<List<MyMembership>>((ref) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).myMemberships();
});

/// Assigned jobs plus pending invitations for organizations I administer, a page at a
/// time: both lists share the server's limit/offset, and "Load more" reads the next page
/// of each.
final contractorInboxProvider =
    AsyncNotifierProvider.autoDispose<ContractorInboxController, PagedInbox>(ContractorInboxController.new);

class PagedInbox {
  const PagedInbox({required this.inbox, required this.hasMore, this.loadingMore = false, this.moreError});

  final ContractorInbox inbox;
  final bool hasMore;
  final bool loadingMore;
  final Object? moreError;
}

class ContractorInboxController extends AsyncNotifier<PagedInbox> {
  int _offset = 0;

  int get _limit => ref.read(listPageSizeProvider('inbox'));

  bool _full(ContractorInbox page, int limit) => page.assigned.length >= limit || page.invitations.length >= limit;

  @override
  Future<PagedInbox> build() async {
    requireUserId(ref);
    final api = ref.watch(contractorsApiProvider);
    final limit = _limit;
    final first = await api.inbox(limit: limit);
    _offset = limit;
    return PagedInbox(inbox: first, hasMore: _full(first, limit));
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.loadingMore) return;
    state = AsyncData(PagedInbox(inbox: current.inbox, hasMore: true, loadingMore: true));
    final limit = _limit;
    try {
      final next = await ref.read(contractorsApiProvider).inbox(limit: limit, offset: _offset);
      if (!ref.mounted) return;
      _offset += limit;
      final jobs = {for (final j in current.inbox.assigned) j.assignmentId};
      final invites = {for (final i in current.inbox.invitations) i.assignmentId};
      state = AsyncData(PagedInbox(
        inbox: ContractorInbox(
          assigned: [...current.inbox.assigned, ...next.assigned.where((j) => !jobs.contains(j.assignmentId))],
          invitations: [
            ...current.inbox.invitations,
            ...next.invitations.where((i) => !invites.contains(i.assignmentId)),
          ],
        ),
        hasMore: _full(next, limit),
      ));
    } catch (e) {
      if (!ref.mounted) return;
      state = AsyncData(PagedInbox(inbox: current.inbox, hasMore: true, moreError: e));
    }
  }
}

final orgInvitationsProvider = FutureProvider.autoDispose.family<List<InvitationSummary>, String>((ref, orgId) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).orgInvitations(orgId);
});

final orgMembersProvider = FutureProvider.autoDispose.family<List<OrgMember>, String>((ref, orgId) {
  requireUserId(ref);
  return ref.watch(contractorsApiProvider).orgMembers(orgId);
});

/// Directory search (owner sharing), a page at a time. A listing grants no access.
final directoryProvider =
    AsyncNotifierProvider.autoDispose.family<DirectoryController, Paged<DirectoryEntry>, String>(DirectoryController.new);

class DirectoryController extends PagedNotifier<DirectoryEntry> {
  DirectoryController(this.query);

  final String query;

  @override
  String get listName => 'directory';

  @override
  Future<Paged<DirectoryEntry>> build() {
    requireUserId(ref);
    ref.watch(contractorsApiProvider);
    return super.build();
  }

  @override
  Future<List<DirectoryEntry>> fetchPage({required int offset, required int limit}) =>
      ref.read(contractorsApiProvider).directory(query: query, limit: limit, offset: offset);
}
