import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/checklists/providers/checklist_provider.dart';
import 'package:helm_marine/features/checklists/screens/vessel_checklists_screen.dart';

void main() {
  group('VesselChecklistsScreen', () {
    Widget buildTestWidget({
      AsyncValue<List<Map<String, dynamic>>>? checklistsState,
    }) {
      return ProviderScope(
        overrides: [
          if (checklistsState != null)
            vesselChecklistsProvider('vessel-1').overrideWith((ref) async {
              if (checklistsState is AsyncError) throw checklistsState.error!;
              return checklistsState.value!;
            }),
        ],
        child: const MaterialApp(
          home: VesselChecklistsScreen(vesselId: 'vessel-1'),
        ),
      );
    }

    testWidgets('shows Voyage Checklists title in app bar', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Voyage Checklists'), findsOneWidget);
    });

    testWidgets('shows empty state with generate button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('No checklists yet'), findsOneWidget);
      expect(find.text('Generate Checklists'), findsOneWidget);
    });

    testWidgets('shows checklist sections when data loaded', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([
          {
            'id': 'c-1',
            'tier': 'grab_and_go',
            'name': 'Grab & Go Kit (Day Trips)',
            'items': [
              {
                'id': 'i-1',
                'system': 'Engine',
                'item_name': 'Spare Spark Plugs',
                'is_checked': false,
                'product_id': null,
                'quantity': 1,
              },
              {
                'id': 'i-2',
                'system': 'General',
                'item_name': 'Duct Tape',
                'is_checked': true,
                'product_id': 'prod-1',
                'quantity': 1,
              },
            ],
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Grab & Go Kit (Day Trips)'), findsOneWidget);
      expect(find.text('1 / 2 completed'), findsOneWidget);
    });

    testWidgets('shows Add Missing to Cart FAB when checklists exist',
        (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([
          {
            'id': 'c-1',
            'tier': 'grab_and_go',
            'name': 'Grab & Go Kit',
            'items': [
              {
                'id': 'i-1',
                'system': 'Engine',
                'item_name': 'Test Item',
                'is_checked': false,
                'product_id': null,
                'quantity': 1,
              },
            ],
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Add Missing to Cart'), findsOneWidget);
      expect(find.byIcon(Icons.add_shopping_cart), findsOneWidget);
    });

    testWidgets('does not show FAB when no checklists', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Add Missing to Cart'), findsNothing);
    });

    testWidgets('shows error state with retry button', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState:
            AsyncError(Exception('Network error'), StackTrace.current),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Retry'), findsOneWidget);
      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });

    testWidgets('shows item names and system labels in expanded tile',
        (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([
          {
            'id': 'c-1',
            'tier': 'grab_and_go',
            'name': 'Grab & Go Kit',
            'items': [
              {
                'id': 'i-1',
                'system': 'Engine (Outboard)',
                'item_name': 'Spare Spark Plugs',
                'is_checked': false,
                'product_id': null,
                'quantity': 2,
              },
            ],
          },
        ]),
      ));
      await tester.pumpAndSettle();

      // Expand the tile
      await tester.tap(find.text('Grab & Go Kit'));
      await tester.pumpAndSettle();

      expect(find.text('Spare Spark Plugs'), findsOneWidget);
      expect(find.text('Engine (Outboard)'), findsOneWidget);
      expect(find.text('x2'), findsOneWidget);
    });

    testWidgets('shows link icon for linked product', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([
          {
            'id': 'c-1',
            'tier': 'grab_and_go',
            'name': 'Grab & Go Kit',
            'items': [
              {
                'id': 'i-1',
                'system': 'Engine',
                'item_name': 'Linked Item',
                'is_checked': false,
                'product_id': 'prod-123',
                'quantity': 1,
              },
            ],
          },
        ]),
      ));
      await tester.pumpAndSettle();

      // Expand the tile
      await tester.tap(find.text('Grab & Go Kit'));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.link), findsOneWidget);
    });

    testWidgets('shows multiple tier sections', (tester) async {
      await tester.pumpWidget(buildTestWidget(
        checklistsState: const AsyncData([
          {
            'id': 'c-1',
            'tier': 'grab_and_go',
            'name': 'Grab & Go Kit (Day Trips)',
            'items': [],
          },
          {
            'id': 'c-2',
            'tier': 'coastal_cruising',
            'name': 'Coastal Cruising Kit (Weekend & Multi-Day)',
            'items': [],
          },
          {
            'id': 'c-3',
            'tier': 'offshore_passage',
            'name': 'Offshore Passage Kit (Extended Voyages)',
            'items': [],
          },
        ]),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Grab & Go Kit (Day Trips)'), findsOneWidget);
      expect(
          find.text('Coastal Cruising Kit (Weekend & Multi-Day)'), findsOneWidget);
      expect(
          find.text('Offshore Passage Kit (Extended Voyages)'), findsOneWidget);
    });
  });
}
