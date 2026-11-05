import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

double _num(Map<String, dynamic> json, String key) {
  final v = json[key];
  if (v is num) return v.toDouble();
  throw FormatException('Field "$key": expected number, got ${v.runtimeType}');
}

/// `PointsSummary` (`GET /loyalty/points`). The tier is display-only.
class PointsSummary {
  const PointsSummary({
    required this.pointsBalance,
    required this.lifetimeEarned,
    required this.pointsValueCents,
    required this.currency,
    required this.tier,
    required this.tierIsDisplayOnly,
    required this.trailing12MonthSpendCents,
    this.nextTier,
    this.nextTierThresholdCents,
    this.crewId,
    this.crewWalletPoints,
    this.pointsOwed = 0,
    this.pointsPerDollar = 100,
  });

  final int pointsBalance;
  final int lifetimeEarned;
  final int pointsValueCents;
  final String currency;
  final String tier;
  final bool tierIsDisplayOnly;
  final int trailing12MonthSpendCents;
  final String? nextTier;
  final int? nextTierThresholdCents;
  final String? crewId;

  /// Display aggregate of the crew members' balances (null when not in a crew).
  final int? crewWalletPoints;

  /// Points still owed after a refund reversed points that were already
  /// redeemed; later credits settle it first. Optional (older API versions
  /// omit it) and 0 when nothing is owed.
  final int pointsOwed;

  /// Server redemption rate (Crew Points per NZ\$1 of discount).
  final int pointsPerDollar;

  String get valueText => formatCents(pointsValueCents, currency: currency);

  factory PointsSummary.fromJson(Map<String, dynamic> json) => PointsSummary(
        pointsBalance: req<int>(json, 'points_balance'),
        lifetimeEarned: req<int>(json, 'lifetime_earned'),
        pointsValueCents: centsFrom(json, 'points_value_cents'),
        currency: req<String>(json, 'currency'),
        tier: req<String>(json, 'tier'),
        tierIsDisplayOnly: req<bool>(json, 'tier_is_display_only'),
        trailing12MonthSpendCents: centsFrom(json, 'trailing_12_month_spend_cents'),
        nextTier: opt<String>(json, 'next_tier'),
        nextTierThresholdCents: optionalCentsFrom(json, 'next_tier_threshold_cents'),
        crewId: opt<String>(json, 'crew_id'),
        crewWalletPoints: opt<int>(json, 'crew_wallet_points'),
        pointsOwed: opt<int>(json, 'points_owed') ?? 0,
        pointsPerDollar: opt<int>(json, 'points_per_dollar') ?? 100,
      );
}

/// One ledger row (`PointsTransactionOut`).
class PointsTransaction {
  const PointsTransaction({
    required this.id,
    required this.kind,
    required this.points,
    required this.balanceAfter,
    required this.createdAt,
    this.description,
    this.orderId,
    this.entitlementId,
    this.redemptionId,
    this.teamId,
    this.period,
    this.eligibleSpendCents,
  });

  final String id;
  final String kind;
  final int points;
  final int balanceAfter;
  final String? description;
  final String? orderId;
  final String? entitlementId;
  final String? redemptionId;
  final String? teamId;
  final String? period;
  final int? eligibleSpendCents;
  final DateTime createdAt;

  /// Human label for [kind] (unknown kinds are shown as-is, humanised).
  String get kindLabel => switch (kind) {
        'earn' => 'Points earned',
        'earn_reversal' => 'Earned points reversed',
        'monthly_bonus' => 'Crew multiplier bonus',
        'redeem_discount' => 'Discount redeemed',
        'redeem_experience' => 'Experience redeemed',
        'redemption_reversal' => 'Points restored',
        'profile_verification_bonus' => 'Vessel profile verified bonus',
        _ => kind.replaceAll('_', ' ').replaceFirstMapped(RegExp(r'^\w'), (m) => m[0]!.toUpperCase()),
      };

  factory PointsTransaction.fromJson(Map<String, dynamic> json) => PointsTransaction(
        id: req<String>(json, 'id'),
        kind: req<String>(json, 'kind'),
        points: req<int>(json, 'points'),
        balanceAfter: req<int>(json, 'balance_after'),
        description: opt<String>(json, 'description'),
        orderId: opt<String>(json, 'order_id'),
        entitlementId: opt<String>(json, 'entitlement_id'),
        redemptionId: opt<String>(json, 'redemption_id'),
        teamId: opt<String>(json, 'team_id'),
        period: opt<String>(json, 'period'),
        eligibleSpendCents: optionalCentsFrom(json, 'eligible_spend_cents'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `TransactionPage` (`GET /loyalty/transactions?limit&offset`).
class TransactionPage {
  const TransactionPage({required this.items, required this.total, required this.limit, required this.offset});

  final List<PointsTransaction> items;
  final int total;
  final int limit;
  final int offset;

  bool get hasMore => offset + items.length < total;

  factory TransactionPage.fromJson(Map<String, dynamic> json) => TransactionPage(
        items: [for (final t in mapList(json, 'items')) PointsTransaction.fromJson(t)],
        total: req<int>(json, 'total'),
        limit: req<int>(json, 'limit'),
        offset: req<int>(json, 'offset'),
      );
}

/// A monthly crew spend threshold and its multiplier.
class MultiplierTier {
  const MultiplierTier({required this.minSpendCents, required this.multiplier});

  final int minSpendCents;
  final double multiplier;

  factory MultiplierTier.fromJson(Map<String, dynamic> json) => MultiplierTier(
        minSpendCents: centsFrom(json, 'min_spend_cents'),
        multiplier: _num(json, 'multiplier'),
      );
}

/// `MultiplierProgress` (`GET /loyalty/multiplier`): this month's crew progress,
/// counting paid orders only.
class MultiplierProgress {
  const MultiplierProgress({
    required this.period,
    required this.memberCount,
    required this.eligibleForMultiplier,
    required this.minMembers,
    required this.crewSpendCents,
    required this.currency,
    required this.currentMultiplier,
    required this.spendMultiplier,
    required this.tiers,
    this.crewId,
    this.nextThresholdCents,
    this.nextMultiplier,
    this.remainingToNextCents,
  });

  final String period;
  final String? crewId;
  final int memberCount;
  final bool eligibleForMultiplier;
  final int minMembers;
  final int crewSpendCents;
  final String currency;
  final double currentMultiplier;
  final double spendMultiplier;
  final int? nextThresholdCents;
  final double? nextMultiplier;
  final int? remainingToNextCents;
  final List<MultiplierTier> tiers;

  /// Progress (0–1) from the current tier's threshold towards the next one.
  double get progressToNext {
    final next = nextThresholdCents;
    if (next == null) return 1;
    var floor = 0;
    for (final t in tiers) {
      if (t.minSpendCents <= crewSpendCents && t.minSpendCents > floor) floor = t.minSpendCents;
    }
    final span = next - floor;
    if (span <= 0) return 1;
    return ((crewSpendCents - floor) / span).clamp(0.0, 1.0);
  }

  factory MultiplierProgress.fromJson(Map<String, dynamic> json) => MultiplierProgress(
        period: req<String>(json, 'period'),
        crewId: opt<String>(json, 'crew_id'),
        memberCount: req<int>(json, 'member_count'),
        eligibleForMultiplier: req<bool>(json, 'eligible_for_multiplier'),
        minMembers: req<int>(json, 'min_members'),
        crewSpendCents: centsFrom(json, 'crew_spend_cents'),
        currency: req<String>(json, 'currency'),
        currentMultiplier: _num(json, 'current_multiplier'),
        spendMultiplier: _num(json, 'spend_multiplier'),
        nextThresholdCents: optionalCentsFrom(json, 'next_threshold_cents'),
        nextMultiplier: optDouble(json, 'next_multiplier'),
        remainingToNextCents: optionalCentsFrom(json, 'remaining_to_next_cents'),
        tiers: [for (final t in mapList(json, 'tiers')) MultiplierTier.fromJson(t)],
      );
}

/// `CrewMemberOut`.
class CrewMember {
  const CrewMember({
    required this.userId,
    required this.displayName,
    required this.role,
    required this.joinedAt,
    required this.pointsBalance,
    required this.isYou,
  });

  final String userId;
  final String displayName;

  /// `captain` or `member`.
  final String role;
  final DateTime joinedAt;
  final int pointsBalance;
  final bool isYou;

  bool get isCaptain => role == 'captain';

  factory CrewMember.fromJson(Map<String, dynamic> json) => CrewMember(
        userId: req<String>(json, 'user_id'),
        displayName: req<String>(json, 'display_name'),
        role: req<String>(json, 'role'),
        joinedAt: reqDate(json, 'joined_at'),
        pointsBalance: req<int>(json, 'points_balance'),
        isYou: req<bool>(json, 'is_you'),
      );
}

/// `CrewOut` (`GET /loyalty/crews/mine`).
class Crew {
  const Crew({
    required this.id,
    required this.name,
    required this.myRole,
    required this.members,
    required this.memberCount,
    required this.pendingInviteCount,
    required this.maxMembers,
    required this.walletPoints,
    required this.walletNote,
    required this.createdAt,
  });

  final String id;
  final String name;
  final String myRole;
  final List<CrewMember> members;
  final int memberCount;
  final int pendingInviteCount;
  final int maxMembers;
  final int walletPoints;
  final String walletNote;
  final DateTime createdAt;

  bool get iAmCaptain => myRole == 'captain';

  factory Crew.fromJson(Map<String, dynamic> json) => Crew(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        myRole: req<String>(json, 'my_role'),
        members: [for (final m in mapList(json, 'members')) CrewMember.fromJson(m)],
        memberCount: req<int>(json, 'member_count'),
        pendingInviteCount: req<int>(json, 'pending_invite_count'),
        maxMembers: req<int>(json, 'max_members'),
        walletPoints: req<int>(json, 'wallet_points'),
        walletNote: req<String>(json, 'wallet_note'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `CrewInviteOut` (as the captain sees it).
class CrewInvite {
  const CrewInvite({
    required this.id,
    required this.invitedEmail,
    required this.status,
    required this.expiresAt,
    required this.createdAt,
  });

  final String id;
  final String invitedEmail;
  final String status;
  final DateTime expiresAt;
  final DateTime createdAt;

  factory CrewInvite.fromJson(Map<String, dynamic> json) => CrewInvite(
        id: req<String>(json, 'id'),
        invitedEmail: req<String>(json, 'invited_email'),
        status: req<String>(json, 'status'),
        expiresAt: reqDate(json, 'expires_at'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `MyInviteOut` (as the invitee sees it).
class MyInvite {
  const MyInvite({
    required this.id,
    required this.crewId,
    required this.crewName,
    required this.status,
    required this.expiresAt,
    required this.createdAt,
    this.invitedByName,
  });

  final String id;
  final String crewId;
  final String crewName;
  final String? invitedByName;
  final String status;
  final DateTime expiresAt;
  final DateTime createdAt;

  factory MyInvite.fromJson(Map<String, dynamic> json) => MyInvite(
        id: req<String>(json, 'id'),
        crewId: req<String>(json, 'crew_id'),
        crewName: req<String>(json, 'crew_name'),
        invitedByName: opt<String>(json, 'invited_by_name'),
        status: req<String>(json, 'status'),
        expiresAt: reqDate(json, 'expires_at'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `LeaveResult` (`POST /loyalty/crews/mine/leave`).
class LeaveResult {
  const LeaveResult({required this.leftCrewId, required this.disbanded, this.newCaptainId});

  final String leftCrewId;
  final bool disbanded;
  final String? newCaptainId;

  factory LeaveResult.fromJson(Map<String, dynamic> json) => LeaveResult(
        leftCrewId: req<String>(json, 'left_crew_id'),
        disbanded: req<bool>(json, 'disbanded'),
        newCaptainId: opt<String>(json, 'new_captain_id'),
      );
}

/// A single-use discount bought with points (`EntitlementOut`).
class Entitlement {
  const Entitlement({
    required this.id,
    required this.code,
    required this.amountCents,
    required this.pointsCost,
    required this.status,
    required this.createdAt,
    required this.currency,
    this.orderId,
    this.reservedAt,
    this.consumedAt,
    this.voidedAt,
  });

  final String id;
  final String code;
  final int amountCents;
  final int pointsCost;

  /// `issued`, `reserved`, `consumed` or `voided`.
  final String status;
  final String? orderId;
  final DateTime createdAt;
  final DateTime? reservedAt;
  final DateTime? consumedAt;
  final DateTime? voidedAt;
  final String currency;

  bool get canVoid => status == 'issued';
  String get amountText => formatCents(amountCents, currency: currency);

  factory Entitlement.fromJson(Map<String, dynamic> json) => Entitlement(
        id: req<String>(json, 'id'),
        code: req<String>(json, 'code'),
        amountCents: centsFrom(json, 'amount_cents'),
        pointsCost: req<int>(json, 'points_cost'),
        status: req<String>(json, 'status'),
        orderId: opt<String>(json, 'order_id'),
        createdAt: reqDate(json, 'created_at'),
        reservedAt: _optDate(json, 'reserved_at'),
        consumedAt: _optDate(json, 'consumed_at'),
        voidedAt: _optDate(json, 'voided_at'),
        currency: opt<String>(json, 'currency') ?? 'NZD',
      );
}

/// A Signature Experience (`Experience`).
class Experience {
  const Experience({
    required this.id,
    required this.title,
    required this.description,
    required this.pointsCost,
    required this.available,
    required this.isSynthetic,
    this.location,
    this.capacity,
    this.imageUrl,
  });

  final String id;
  final String title;
  final String description;
  final int pointsCost;
  final String? location;
  final int? capacity;
  final bool available;
  final String? imageUrl;
  final bool isSynthetic;

  factory Experience.fromJson(Map<String, dynamic> json) => Experience(
        id: req<String>(json, 'id'),
        title: req<String>(json, 'title'),
        description: req<String>(json, 'description'),
        pointsCost: req<int>(json, 'points_cost'),
        location: opt<String>(json, 'location'),
        capacity: opt<int>(json, 'capacity'),
        available: req<bool>(json, 'available'),
        imageUrl: opt<String>(json, 'image_url'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
      );
}

/// `ExperienceCatalogue`. When [available] is false there are no items and
/// [reason] says why — nothing is substituted.
class ExperienceCatalogue {
  const ExperienceCatalogue({required this.available, required this.provider, required this.items, this.reason});

  final bool available;
  final String provider;
  final List<Experience> items;
  final String? reason;

  factory ExperienceCatalogue.fromJson(Map<String, dynamic> json) {
    final available = req<bool>(json, 'available');
    return ExperienceCatalogue(
      available: available,
      provider: req<String>(json, 'provider'),
      // Never show items from an unavailable catalogue.
      items: available ? [for (final e in mapList(json, 'items')) Experience.fromJson(e)] : const [],
      reason: opt<String>(json, 'reason'),
    );
  }
}

/// An experience redemption record (`RedemptionOut` / `AdminRedemptionOut`).
class Redemption {
  const Redemption({
    required this.id,
    required this.experienceId,
    required this.experienceTitle,
    required this.pointsCost,
    required this.cmsProvider,
    required this.isSynthetic,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    this.customerNote,
    this.fulfilledAt,
    this.userId,
    this.staffNote,
    this.handledBy,
  });

  final String id;
  final String experienceId;
  final String experienceTitle;
  final int pointsCost;
  final String cmsProvider;
  final bool isSynthetic;

  /// `requested`, `confirmed`, `fulfilled` or `cancelled`.
  final String status;
  final String? customerNote;
  final DateTime? fulfilledAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  // Admin view only.
  final String? userId;
  final String? staffNote;
  final String? handledBy;

  bool get canConfirm => status == 'requested';
  bool get canFulfil => status == 'confirmed';
  bool get canCancel => status == 'requested' || status == 'confirmed';

  factory Redemption.fromJson(Map<String, dynamic> json) => Redemption(
        id: req<String>(json, 'id'),
        experienceId: req<String>(json, 'experience_id'),
        experienceTitle: req<String>(json, 'experience_title'),
        pointsCost: req<int>(json, 'points_cost'),
        cmsProvider: req<String>(json, 'cms_provider'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        status: req<String>(json, 'status'),
        customerNote: opt<String>(json, 'customer_note'),
        fulfilledAt: _optDate(json, 'fulfilled_at'),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
        userId: opt<String>(json, 'user_id'),
        staffNote: opt<String>(json, 'staff_note'),
        handledBy: opt<String>(json, 'handled_by'),
      );
}
