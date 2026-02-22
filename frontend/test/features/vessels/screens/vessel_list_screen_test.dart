import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/features/vessels/screens/vessel_list_screen.dart';

void main() {
  group('VesselListScreen', () {
    Widget buildTestWidget({required AsyncValue<List<Vessel>> vesselsState}) {
      return ProviderScope(
        overrides: [
          vesselListProvider.overrideWith(() => _FakeVesselNotifier(vesselsState)),
        ],
        child: const MaterialApp(
          home: VesselListScreen(),
        ),
      );
    }

    testWidgets('shows empty state when no vessels', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(vesselsState: const AsyncData([])),
      );

      expect(find.text('No vessels in your garage'), findsOneWidget);
      expect(find.text('Add Vessel'), findsOneWidget);
    });

    testWidgets('shows loading indicator', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(vesselsState: const AsyncLoading()),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows vessel list', (tester) async {
      final vessels = [
        Vessel(
          id: 'v1',
          userId: 'u1',
          name: 'Sea Breeze',
          make: 'Stabicraft',
          model: '1850 Fisher',
          year: 2022,
          isPrimary: true,
          createdAt: DateTime.now(),
        ),
        Vessel(
          id: 'v2',
          userId: 'u1',
          name: 'Ocean Runner',
          make: 'Haines Hunter',
          model: 'SF600',
          isPrimary: false,
          createdAt: DateTime.now(),
        ),
      ];

      await tester.pumpWidget(
        buildTestWidget(vesselsState: AsyncData(vessels)),
      );

      expect(find.text('Sea Breeze'), findsOneWidget);
      expect(find.text('Ocean Runner'), findsOneWidget);
      expect(find.text('Stabicraft 1850 Fisher (2022)'), findsOneWidget);
      expect(find.text('Primary'), findsOneWidget);
    });

    testWidgets('shows error state', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(
          vesselsState: AsyncError('Network error', StackTrace.current),
        ),
      );

      expect(find.text('Failed to load vessels'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('has floating action button to add vessel', (tester) async {
      await tester.pumpWidget(
        buildTestWidget(vesselsState: const AsyncData([])),
      );

      expect(find.byType(FloatingActionButton), findsOneWidget);
    });
  });
}

class _FakeVesselNotifier extends VesselListNotifier {
  final AsyncValue<List<Vessel>> _initial;

  _FakeVesselNotifier(this._initial);

  @override
  Future<List<Vessel>> build() async {
    state = _initial;
    return _initial.valueOrNull ?? [];
  }
}
