import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/loyalty/data/loyalty_api.dart';

/// Crew Points balance, display-only tier and the Crew Wallet aggregate.
final pointsSummaryProvider = FutureProvider.autoDispose<PointsSummary>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).points();
});

/// This month's crew multiplier progress (paid spend only) with the server's tiers.
final multiplierProgressProvider = FutureProvider.autoDispose<MultiplierProgress>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).multiplier();
});

/// The user's crew, or null when they are not in one.
final myCrewProvider = FutureProvider.autoDispose<Crew?>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).myCrew();
});

/// Pending invites of the captain's crew.
final crewInvitesProvider = FutureProvider.autoDispose<List<CrewInvite>>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).crewInvites();
});

/// Pending invites addressed to the signed-in user's verified email.
final myInvitesProvider = FutureProvider.autoDispose<List<MyInvite>>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).myInvites();
});

final entitlementsProvider = FutureProvider.autoDispose<List<Entitlement>>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).entitlements();
});

/// The authoritative Signature Experiences catalogue (no items when unavailable).
final experienceCatalogueProvider = FutureProvider.autoDispose<ExperienceCatalogue>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).experiences();
});

final myRedemptionsProvider = FutureProvider.autoDispose<List<Redemption>>((ref) {
  requireUserId(ref);
  return ref.watch(loyaltyApiProvider).redemptions();
});

/// Page size of the points ledger.
const transactionPageSize = 20;

/// The points ledger, newest first, loaded a page at a time.
class TransactionLedger {
  const TransactionLedger({required this.items, required this.total, this.loadingMore = false, this.moreError});

  final List<PointsTransaction> items;
  final int total;
  final bool loadingMore;
  final Object? moreError;

  bool get hasMore => items.length < total;
}

final transactionLedgerProvider =
    AsyncNotifierProvider.autoDispose<TransactionLedgerNotifier, TransactionLedger>(TransactionLedgerNotifier.new);

class TransactionLedgerNotifier extends AsyncNotifier<TransactionLedger> {
  @override
  Future<TransactionLedger> build() async {
    requireUserId(ref);
    final page = await ref.watch(loyaltyApiProvider).transactions(limit: transactionPageSize);
    return TransactionLedger(items: page.items, total: page.total);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.loadingMore) return;
    state = AsyncData(TransactionLedger(items: current.items, total: current.total, loadingMore: true));
    try {
      final page = await ref
          .read(loyaltyApiProvider)
          .transactions(limit: transactionPageSize, offset: current.items.length);
      if (!ref.mounted) return;
      state = AsyncData(TransactionLedger(items: [...current.items, ...page.items], total: page.total));
    } catch (e) {
      if (!ref.mounted) return;
      state = AsyncData(TransactionLedger(items: current.items, total: current.total, moreError: e));
    }
  }
}

/// Refreshes everything a points-changing action can affect.
void refreshRewards(WidgetRef ref) {
  ref.invalidate(pointsSummaryProvider);
  ref.invalidate(transactionLedgerProvider);
  ref.invalidate(entitlementsProvider);
  ref.invalidate(myRedemptionsProvider);
  ref.invalidate(myCrewProvider);
  ref.invalidate(multiplierProgressProvider);
}

/// Refreshes crew membership views.
void refreshCrew(WidgetRef ref) {
  ref.invalidate(myCrewProvider);
  ref.invalidate(crewInvitesProvider);
  ref.invalidate(myInvitesProvider);
  ref.invalidate(pointsSummaryProvider);
  ref.invalidate(multiplierProgressProvider);
}
