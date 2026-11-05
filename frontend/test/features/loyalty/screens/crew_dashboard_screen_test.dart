// Crew Rewards in the real app shell, fed with captured server payloads.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/features/loyalty/providers/loyalty_provider.dart';
import 'package:helm_marine/features/loyalty/screens/crew_dashboard_screen.dart';

import '../../../helpers/fakes.dart';
import '../../content/engagement_test_helpers.dart';

/// A backend for a captain with points, a crew, invites and redemptions.
FakeBackend rewardsBackend() {
  final b = engagementBackend();
  b.json('GET /loyalty/points', 200, eng('loyalty_points_in_crew'));
  b.json('GET /loyalty/multiplier', 200, eng('loyalty_multiplier'));
  b.json('GET /loyalty/transactions', 200, eng('loyalty_transactions'));
  b.json('GET /loyalty/crews/mine', 200, eng('loyalty_crew_captain_view'));
  b.json('GET /loyalty/crews/mine/invites', 200, eng('loyalty_crew_invites'));
  b.json('GET /loyalty/invites', 200, eng('loyalty_invites_empty'));
  b.json('GET /loyalty/entitlements', 200, eng('loyalty_entitlements'));
  b.json('GET /loyalty/experiences', 200, eng('loyalty_experiences'));
  b.json('GET /loyalty/redemptions', 200, eng('loyalty_redemptions'));
  return b;
}

Future<dynamic> openCrew(WidgetTester tester, FakeBackend backend) async {
  final app = await engagementApp(tester, backend: backend, size: const Size(1000, 2400));
  app.go('/crew');
  await app.settle();
  return app;
}

void main() {
  testWidgets('points tab: balance, display-only tier, wallet aggregate, multiplier, paginated ledger', (tester) async {
    final backend = rewardsBackend();
    backend.on('GET /loyalty/transactions', (r) => FakeResponse(
        200, r.query['offset'] == '0' ? eng('loyalty_transactions') : eng('loyalty_transactions_page2')));
    final app = await openCrew(tester, backend);
    final points = engMap('loyalty_points_in_crew');

    expect(find.text('${points['points_balance']} CP'), findsWidgets);
    expect(find.text('Mate tier'), findsOneWidget);
    expect(find.textContaining('recognition only'), findsOneWidget);
    expect(find.textContaining('Crew Wallet: ${points['crew_wallet_points']} CP'), findsOneWidget);
    expect(find.textContaining('each member redeems only their own points'), findsOneWidget);
    expect(find.text('1.0×'), findsWidgets);
    expect(find.textContaining('(paid orders only)'), findsOneWidget);
    expect(find.text(r'$500.00+'), findsOneWidget); // server tier table
    expect(find.text('Experience redeemed'), findsOneWidget);

    final total = engMap('loyalty_transactions')['total'];
    await app.tap(find.text('Load more (3 of $total)'));
    expect(backend.calls('GET /loyalty/transactions').last.query['offset'], '3');
    expect(find.text('Points earned'), findsOneWidget);
    expect(find.textContaining('Load more'), findsNothing);
  });

  testWidgets('crew tab (captain): captain badge, invite, revoke, remove, leave explains hand-over', (tester) async {
    final backend = rewardsBackend();
    final crew = engMap('loyalty_crew_captain_view');
    final mate = (crew['members'] as List).cast<Map>().firstWhere((m) => m['is_you'] == false);
    final invites = engList('loyalty_crew_invites');
    backend.json('POST /loyalty/crews/mine/invites', 201, eng('loyalty_crew_invite_created'));
    backend.json('DELETE /loyalty/crews/mine/invites/${invites.last['id']}', 200, eng('loyalty_crew_invite_revoked'));
    backend.json('DELETE /loyalty/crews/mine/members/${mate['user_id']}', 204, null);
    backend.json('POST /loyalty/crews/mine/leave', 200, eng('loyalty_leave_handover'));
    final app = await openCrew(tester, backend);
    await app.tap(find.text('Crew'));

    expect(find.text(crew['name'] as String), findsOneWidget);
    expect(find.text('Captain'), findsOneWidget);
    expect(find.text('Fixture Skipper (you)'), findsOneWidget);
    expect(find.textContaining('You are the captain'), findsOneWidget);
    for (final i in invites) {
      expect(find.text(i['invited_email'] as String), findsOneWidget);
    }

    await tester.enterText(find.widgetWithText(TextFormField, 'Email address to invite'), 'not-an-email');
    await app.tap(find.text('Send invite'));
    expect(find.text('Enter an email address'), findsOneWidget);
    expect(backend.calls('POST /loyalty/crews/mine/invites'), isEmpty);
    await tester.enterText(find.widgetWithText(TextFormField, 'Email address to invite'), 'mate@example.test');
    await app.tap(find.text('Send invite'));
    expect(backend.calls('POST /loyalty/crews/mine/invites').single.body, {'email': 'mate@example.test'});

    await app.tap(find.text('Revoke').last);
    expect(backend.calls('DELETE /loyalty/crews/mine/invites/${invites.last['id']}'), hasLength(1));

    await app.tap(find.byTooltip('Remove ${mate['display_name']}'));
    await app.tap(find.widgetWithText(FilledButton, 'Remove'));
    expect(backend.calls('DELETE /loyalty/crews/mine/members/${mate['user_id']}'), hasLength(1));

    await app.tap(find.text('Leave crew'));
    expect(find.textContaining('Captaincy passes to the longest-serving member (${mate['display_name']})'), findsOneWidget);
    await app.tap(find.widgetWithText(FilledButton, 'Leave crew'));
    expect(backend.calls('POST /loyalty/crews/mine/leave'), hasLength(1));
  });

  testWidgets('crew tab (not in a crew): create crew and the invitee inbox', (tester) async {
    final backend = rewardsBackend();
    backend.json('GET /loyalty/crews/mine', 404, eng('error_not_in_crew'));
    backend.json('GET /loyalty/invites', 200, eng('loyalty_invites'));
    backend.json('POST /loyalty/crews', 201, eng('loyalty_crew_created'));
    final invite = engList('loyalty_invites').single;
    backend.json('POST /loyalty/invites/${invite['id']}/accept', 200, eng('loyalty_invite_accepted'));
    backend.json('POST /loyalty/invites/${invite['id']}/decline', 200, eng('loyalty_invite_declined'));
    final app = await openCrew(tester, backend);
    await app.tap(find.text('Crew'));

    expect(find.text("You're not in a crew yet"), findsOneWidget);
    expect(find.text('Join ${invite['crew_name']}'), findsOneWidget);
    expect(find.textContaining('Invited by Fixture Skipper'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextFormField, 'Crew name'), 'X');
    await app.tap(find.text('Create crew'));
    expect(find.text('Use at least 2 characters'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextFormField, 'Crew name'), 'Hauraki Hookers');
    await app.tap(find.text('Create crew'));
    expect(backend.calls('POST /loyalty/crews').single.body, {'name': 'Hauraki Hookers'});

    await app.tap(find.text('Accept invite'));
    expect(backend.calls('POST /loyalty/invites/${invite['id']}/accept'), hasLength(1));
  });

  testWidgets('redeem tab: multiples of 100 only, shows the issued code, void restores points', (tester) async {
    final backend = rewardsBackend();
    backend.json('GET /loyalty/points', 200, eng('loyalty_points'));
    backend.json('POST /loyalty/redeem/discount', 201, eng('loyalty_discount_redeemed'));
    final issued = engList('loyalty_entitlements').firstWhere((e) => e['status'] == 'issued');
    backend.json('POST /loyalty/entitlements/${issued['id']}/void', 200, eng('loyalty_entitlement_voided'));
    final app = await openCrew(tester, backend);
    await app.tap(find.text('Redeem'));

    await tester.enterText(find.widgetWithText(TextFormField, 'Points to redeem'), '150');
    await app.tap(find.text('Redeem points'));
    expect(find.text('Use a multiple of 100'), findsOneWidget);
    expect(backend.calls('POST /loyalty/redeem/discount'), isEmpty);

    await tester.enterText(find.widgetWithText(TextFormField, 'Points to redeem'), '100');
    await tester.pump();
    expect(find.text(r'Worth $1.00 off'), findsOneWidget);
    await app.tap(find.text('Redeem points'));
    final call = backend.calls('POST /loyalty/redeem/discount').single;
    expect(call.body, {'points': 100});
    expect(call.headers['Idempotency-Key'], isNotEmpty);
    final code = engMap('loyalty_discount_redeemed')['code'];
    expect(find.text('Discount code $code'), findsOneWidget);

    await app.tap(find.text('Void').first);
    await app.tap(find.widgetWithText(FilledButton, 'Void code'));
    expect(backend.calls('POST /loyalty/entitlements/${issued['id']}/void'), hasLength(1));
  });

  testWidgets('redeem errors surface the server detail', (tester) async {
    final backend = rewardsBackend();
    backend.json('GET /loyalty/points', 200, eng('loyalty_points'));
    backend.json('POST /loyalty/redeem/discount', 409, eng('error_insufficient_points'));
    final app = await openCrew(tester, backend);
    await app.tap(find.text('Redeem'));
    await app.tap(find.text('Redeem points'));
    expect(find.textContaining(engMap('error_insufficient_points')['detail'] as String), findsOneWidget);
  });

  testWidgets('experiences: synthetic badge, unavailable item, redeem with note, my redemptions', (tester) async {
    final backend = rewardsBackend();
    backend.json('GET /loyalty/points', 200, eng('loyalty_points'));
    backend.json('POST /loyalty/redeem/experience', 201, eng('loyalty_experience_redeemed'));
    final app = await openCrew(tester, backend);
    await app.tap(find.text('Experiences'));

    expect(find.text('[SYNTHETIC] Test Harbour Day Trip'), findsWidgets);
    expect(find.text('Synthetic test data'), findsWidgets);
    expect(find.text('Not currently available'), findsOneWidget);
    expect(find.textContaining('You need'), findsWidgets); // expensive items are disabled

    final day = find.ancestor(of: find.text('[SYNTHETIC] Test Harbour Day Trip').first, matching: find.byType(Card)).first;
    await app.tap(find.descendant(of: day, matching: find.text('Redeem experience')));
    await tester.enterText(find.widgetWithText(TextField, 'Note for the Helm team (optional)'), 'Two people, any Saturday');
    await app.tap(find.text('Confirm redemption'));
    expect(backend.calls('POST /loyalty/redeem/experience').single.body,
        {'experience_id': 'synthetic-test-day-trip', 'note': 'Two people, any Saturday'});
    expect(find.text('Redemption requested'), findsOneWidget);
    expect(find.text('Status: Requested · 500 CP'), findsOneWidget);
    await app.tap(find.text('OK'));
    expect(find.text('Requested'), findsWidgets);
  });

  testWidgets('points owed after a refund is shown only when > 0', (tester) async {
    // The running stack predates `points_owed` (the captured payload omits it and
    // parses as 0); the owed state is built at model level.
    final real = PointsSummary.fromJson(engMap('loyalty_points'));
    expect(real.pointsOwed, 0);
    final owed = PointsSummary(
      pointsBalance: 0,
      lifetimeEarned: real.lifetimeEarned,
      pointsValueCents: 0,
      currency: real.currency,
      tier: real.tier,
      tierIsDisplayOnly: true,
      trailing12MonthSpendCents: real.trailing12MonthSpendCents,
      pointsOwed: 250,
    );
    Future<void> pump(PointsSummary p) async {
      await tester.pumpWidget(ProviderScope(
        key: UniqueKey(),
        overrides: [
          ...baseTestOverrides(),
          pointsSummaryProvider.overrideWith((ref) async => p),
          multiplierProgressProvider.overrideWith((ref) async => MultiplierProgress.fromJson(engMap('loyalty_multiplier_no_crew'))),
          myCrewProvider.overrideWith((ref) async => null),
          transactionLedgerProvider.overrideWith(() => _EmptyLedger()),
        ],
        child: const MaterialApp(home: CrewDashboardScreen()),
      ));
      await tester.pumpAndSettle();
    }

    await pump(real);
    expect(find.textContaining('owed from a refunded order'), findsNothing);
    await pump(owed);
    expect(find.text('250 CP owed from a refunded order — settled from your next points'), findsOneWidget);
  });

  testWidgets('an unavailable catalogue shows the reason and no items', (tester) async {
    // Model-level state (the running stack's CMS fixture is available, so the
    // unavailable payload could not be captured); parsing of that shape is
    // covered in loyalty_contract_test.dart.
    await tester.pumpWidget(ProviderScope(
      overrides: [
        ...baseTestOverrides(),
        experienceCatalogueProvider.overrideWith((ref) async =>
            const ExperienceCatalogue(available: false, provider: 'strapi', items: [], reason: 'cms_unreachable')),
        myRedemptionsProvider.overrideWith((ref) async => const <Redemption>[]),
        pointsSummaryProvider.overrideWith((ref) async => PointsSummary.fromJson(engMap('loyalty_points'))),
      ],
      child: const MaterialApp(home: CrewDashboardScreen(initialTab: 3)),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Signature Experiences are unavailable right now'), findsOneWidget);
    expect(find.textContaining('could not be reached'), findsOneWidget);
    expect(find.text('Redeem experience'), findsNothing);
  });
}

class _EmptyLedger extends TransactionLedgerNotifier {
  @override
  Future<TransactionLedger> build() async => const TransactionLedger(items: [], total: 0);
}
