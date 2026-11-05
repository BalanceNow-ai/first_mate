// Contract: Crew Rewards models parse REAL /loyalty/* payloads captured from the
// local stack (points earned by paying an order through the TEST MODE flow).
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/loyalty.dart';

import '../content/engagement_test_helpers.dart';

void main() {
  test('points: empty account, after a paid order, and in a crew', () {
    final empty = PointsSummary.fromJson(engMap('loyalty_points_empty'));
    expect(empty.pointsBalance, 0);
    expect(empty.crewWalletPoints, isNull);
    expect(empty.tierIsDisplayOnly, isTrue);

    final paid = PointsSummary.fromJson(engMap('loyalty_points'));
    expect(paid.pointsBalance, greaterThan(0));
    expect(paid.lifetimeEarned, paid.pointsBalance);
    expect(paid.pointsValueCents, paid.pointsBalance); // 100 CP = $1
    expect(paid.trailing12MonthSpendCents, greaterThan(0));
    expect(paid.nextTier, isNotNull);

    final crew = PointsSummary.fromJson(engMap('loyalty_points_in_crew'));
    expect(crew.crewId, isNotNull);
    expect(crew.crewWalletPoints, isNotNull);
  });

  test('ledger pages, kinds and balances', () {
    final p1 = TransactionPage.fromJson(engMap('loyalty_transactions'));
    final p2 = TransactionPage.fromJson(engMap('loyalty_transactions_page2'));
    expect(p1.limit, 3);
    expect(p1.items, hasLength(3));
    expect(p1.hasMore, isTrue);
    expect(p2.offset, 3);
    expect(p2.hasMore, isFalse);
    final all = [...p1.items, ...p2.items];
    expect(all.map((t) => t.kind), containsAll(['earn', 'redeem_discount', 'redemption_reversal', 'redeem_experience']));
    final earn = all.singleWhere((t) => t.kind == 'earn');
    expect(earn.orderId, isNotNull);
    expect(earn.kindLabel, 'Points earned');
    expect(TransactionPage.fromJson(engMap('loyalty_transactions_empty')).items, isEmpty);
    final member = TransactionPage.fromJson(engMap('loyalty_transactions_member'));
    expect(member.items.map((t) => t.kind), contains('profile_verification_bonus'));
  });

  test('multiplier progress with server tiers', () {
    final m = MultiplierProgress.fromJson(engMap('loyalty_multiplier'));
    expect(m.tiers.first.minSpendCents, 0);
    expect(m.tiers.length, greaterThan(1));
    expect(m.eligibleForMultiplier, isTrue);
    expect(m.memberCount, greaterThanOrEqualTo(m.minMembers));
    expect(m.progressToNext, inInclusiveRange(0, 1));
    final none = MultiplierProgress.fromJson(engMap('loyalty_multiplier_no_crew'));
    expect(none.crewId, isNull);
    expect(none.currentMultiplier, 1.0);
  });

  test('crew views, invites and leave results', () {
    final captain = Crew.fromJson(engMap('loyalty_crew_captain_view'));
    expect(captain.iAmCaptain, isTrue);
    expect(captain.members.where((m) => m.isCaptain), hasLength(1));
    expect(captain.members.singleWhere((m) => m.isYou).isCaptain, isTrue);
    expect(captain.walletNote, contains('only their own points'));
    expect(captain.walletPoints, captain.members.fold<int>(0, (s, m) => s + m.pointsBalance));
    final member = Crew.fromJson(engMap('loyalty_crew_member_view'));
    expect(member.iAmCaptain, isFalse);
    expect(Crew.fromJson(engMap('loyalty_crew_created')).memberCount, 1);
    expect(Crew.fromJson(engMap('loyalty_invite_accepted')).myRole, 'member');

    final invites = [for (final j in engList('loyalty_crew_invites')) CrewInvite.fromJson(j)];
    expect(invites.every((i) => i.status == 'pending'), isTrue);
    expect(CrewInvite.fromJson(engMap('loyalty_crew_invite_created')).status, 'pending');
    expect(CrewInvite.fromJson(engMap('loyalty_crew_invite_revoked')).status, 'revoked');
    final inbox = [for (final j in engList('loyalty_invites')) MyInvite.fromJson(j)];
    expect(inbox.single.invitedByName, 'Fixture Skipper');
    expect(MyInvite.fromJson(engMap('loyalty_invite_declined')).status, 'declined');
    expect(eng('loyalty_invites_empty'), isEmpty);

    final handover = LeaveResult.fromJson(engMap('loyalty_leave_handover'));
    expect(handover.disbanded, isFalse);
    expect(handover.newCaptainId, isNotNull);
    final last = LeaveResult.fromJson(engMap('loyalty_leave_disbanded'));
    expect(last.disbanded, isTrue);
    expect(last.newCaptainId, isNull);
  });

  test('discounts: redeemed, voided, listed', () {
    final e = Entitlement.fromJson(engMap('loyalty_discount_redeemed'));
    expect(e.status, 'issued');
    expect(e.canVoid, isTrue);
    expect(e.amountCents, 100);
    expect(e.amountText, r'$1.00');
    expect(e.code, startsWith('CREW-'));
    final voided = Entitlement.fromJson(engMap('loyalty_entitlement_voided'));
    expect(voided.status, 'voided');
    expect(voided.voidedAt, isNotNull);
    final list = [for (final j in engList('loyalty_entitlements')) Entitlement.fromJson(j)];
    expect(list.map((x) => x.status), containsAll(['issued', 'voided']));
  });

  test('experiences and redemptions', () {
    final c = ExperienceCatalogue.fromJson(engMap('loyalty_experiences'));
    expect(c.available, isTrue);
    expect(c.items.every((e) => e.isSynthetic), isTrue);
    expect(c.items.where((e) => !e.available), hasLength(1));
    final r = Redemption.fromJson(engMap('loyalty_experience_redeemed'));
    expect(r.status, 'requested');
    expect(r.customerNote, 'Two people, any Saturday');
    expect(r.canConfirm && r.canCancel && !r.canFulfil, isTrue);
    final mine = [for (final j in engList('loyalty_redemptions')) Redemption.fromJson(j)];
    expect(mine.single.userId, isNull, reason: 'customer view has no admin fields');
  });

  test('an unavailable catalogue never yields items', () {
    // The real payload with the availability flag the server uses when the CMS is down.
    final json = {...engMap('loyalty_experiences'), 'available': false, 'reason': 'cms_unreachable'};
    final c = ExperienceCatalogue.fromJson(json);
    expect(c.items, isEmpty);
    expect(c.reason, 'cms_unreachable');
  });

  test('error payloads carry machine codes and extra fields', () {
    final insufficient = ApiError.fromResponse(409, engMap('error_insufficient_points'));
    expect(insufficient.code, 'insufficient_points');
    expect(insufficient.extra['points_required'], 1000000);
    for (final (name, code) in [
      ('error_invalid_points', 'invalid_points'),
      ('error_not_in_crew', 'not_in_crew'),
      ('error_captain_only', 'captain_only'),
      ('error_use_leave', 'use_leave'),
      ('error_entitlement_not_voidable', 'entitlement_not_voidable'),
      ('error_experience_unavailable', 'experience_unavailable'),
    ]) {
      expect(ApiError.fromResponse(409, engMap(name)).code, code, reason: name);
    }
    final validation = ApiError.fromResponse(422, engMap('error_validation_crew_name'));
    expect(describeError(validation), contains('name'));
  });
}
