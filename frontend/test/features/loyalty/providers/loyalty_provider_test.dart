import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/loyalty/providers/loyalty_provider.dart';

void main() {
  group('MultiplierTier helpers', () {
    test('getCurrentTierName returns Deckhand for 0 spend', () {
      expect(getCurrentTierName(0), 'Deckhand');
    });

    test('getCurrentTierName returns Crew for \$500 spend', () {
      expect(getCurrentTierName(500), 'Crew');
    });

    test('getCurrentTierName returns Bosun for \$1000 spend', () {
      expect(getCurrentTierName(1000), 'Bosun');
    });

    test('getCurrentTierName returns First Mate for \$2000 spend', () {
      expect(getCurrentTierName(2000), 'First Mate');
    });

    test('getCurrentTierName returns Captain for \$5000 spend', () {
      expect(getCurrentTierName(5000), 'Captain');
    });

    test('getCurrentTierName returns Captain for \$10000 spend', () {
      expect(getCurrentTierName(10000), 'Captain');
    });

    test('getNextTier returns Crew for 0 spend', () {
      final next = getNextTier(0);
      expect(next, isNotNull);
      expect(next!.name, 'Crew');
      expect(next.minSpend, 500);
    });

    test('getNextTier returns Bosun for \$500 spend', () {
      final next = getNextTier(500);
      expect(next, isNotNull);
      expect(next!.name, 'Bosun');
      expect(next.minSpend, 1000);
    });

    test('getNextTier returns null at max tier', () {
      final next = getNextTier(5000);
      expect(next, isNull);
    });

    test('multiplierTiers has 5 tiers', () {
      expect(multiplierTiers.length, 5);
    });

    test('multiplierTiers are in ascending order', () {
      for (int i = 1; i < multiplierTiers.length; i++) {
        expect(multiplierTiers[i].minSpend,
            greaterThan(multiplierTiers[i - 1].minSpend));
        expect(multiplierTiers[i].multiplier,
            greaterThan(multiplierTiers[i - 1].multiplier));
      }
    });
  });
}
