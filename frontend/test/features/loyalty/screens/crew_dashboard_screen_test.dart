import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/loyalty/providers/loyalty_provider.dart';
import 'package:helm_marine/features/loyalty/screens/crew_dashboard_screen.dart';

void main() {
  group('CrewDashboardScreen', () {
    Widget buildTestWidget({
      AsyncValue<Map<String, dynamic>>? pointsState,
      AsyncValue<Map<String, dynamic>>? multiplierState,
      AsyncValue<List<Map<String, dynamic>>>? teamsState,
      AsyncValue<List<Map<String, dynamic>>>? experiencesState,
    }) {
      return ProviderScope(
        overrides: [
          if (pointsState != null)
            crewPointsProvider.overrideWith((ref) async {
              if (pointsState is AsyncError) throw pointsState.error!;
              return pointsState.value!;
            }),
          if (multiplierState != null)
            crewMultiplierProvider.overrideWith((ref) async {
              if (multiplierState is AsyncError) throw multiplierState.error!;
              return multiplierState.value!;
            }),
          if (teamsState != null)
            crewTeamsProvider.overrideWith((ref) async {
              if (teamsState is AsyncError) throw teamsState.error!;
              return teamsState.value!;
            }),
          if (experiencesState != null)
            experiencesProvider.overrideWith((ref) async {
              if (experiencesState is AsyncError) throw experiencesState.error!;
              return experiencesState.value!;
            }),
        ],
        child: const MaterialApp(
          home: CrewDashboardScreen(),
        ),
      );
    }

    testWidgets('shows crew rewards title', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState: const AsyncData({'points_balance': 1250, 'tier': 'crew'}),
        multiplierState: const AsyncData({
          'monthly_spend': 750.0,
          'multiplier': 1.25,
        }),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Crew Rewards'), findsOneWidget);
    });

    testWidgets('shows points balance', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 2500, 'tier': 'bosun'}),
        multiplierState: const AsyncData({
          'monthly_spend': 1200.0,
          'multiplier': 1.5,
        }),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('2500 CP'), findsOneWidget);
      expect(find.text('BOSUN'), findsOneWidget);
    });

    testWidgets('shows empty teams message', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 0, 'tier': 'deckhand'}),
        multiplierState:
            const AsyncData({'monthly_spend': 0.0, 'multiplier': 1.0}),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('No crew teams yet'), findsOneWidget);
    });

    testWidgets('shows crew teams', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 500, 'tier': 'deckhand'}),
        multiplierState:
            const AsyncData({'monthly_spend': 0.0, 'multiplier': 1.0}),
        teamsState: const AsyncData([
          {
            'name': 'Ocean Warriors',
            'member_count': 4,
            'crew_wallet_balance': 300,
          },
        ]),
        experiencesState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Ocean Warriors'), findsOneWidget);
      expect(find.text('4 members'), findsOneWidget);
      expect(find.text('300 CP'), findsOneWidget);
    });

    testWidgets('shows dynamic signature experiences from provider',
        (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 0, 'tier': 'deckhand'}),
        multiplierState:
            const AsyncData({'monthly_spend': 0.0, 'multiplier': 1.0}),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([
          {
            'id': 'exp-1',
            'title': 'Harbour Cruise',
            'description': 'Auckland harbour cruise',
            'cost_cp': 5000,
            'location': 'Auckland',
          },
          {
            'id': 'exp-2',
            'title': 'Fishing Charter',
            'description': 'Deep-sea fishing in the Hauraki Gulf',
            'cost_cp': 15000,
            'location': 'Hauraki Gulf',
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Signature Experiences'), findsOneWidget);
      expect(find.text('Harbour Cruise'), findsOneWidget);
      expect(find.text('Fishing Charter'), findsOneWidget);
    });

    testWidgets('shows empty experiences message', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 0, 'tier': 'deckhand'}),
        multiplierState:
            const AsyncData({'monthly_spend': 0.0, 'multiplier': 1.0}),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('No experiences available'), findsOneWidget);
    });

    testWidgets('shows experience cost in CP', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        pointsState:
            const AsyncData({'points_balance': 0, 'tier': 'deckhand'}),
        multiplierState:
            const AsyncData({'monthly_spend': 0.0, 'multiplier': 1.0}),
        teamsState: const AsyncData([]),
        experiencesState: const AsyncData([
          {
            'id': 'exp-1',
            'title': 'Marine Detailing',
            'description': 'Professional hull detail',
            'cost_cp': 8000,
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('8000'), findsOneWidget);
    });
  });
}
