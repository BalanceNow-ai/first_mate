import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_service.dart';

/// Crew Points balance.
final crewPointsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getCrewPoints();
});

/// Current multiplier with tier info.
final crewMultiplierProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getCrewMultiplier();
});

/// Signature Experiences from Strapi.
final experiencesProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getSignatureExperiences();
});

/// User's crew teams.
final crewTeamsProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return apiService.getCrewTeams();
});

/// Multiplier tier thresholds (client-side mirror of backend tiers).
class MultiplierTier {
  final double minSpend;
  final double multiplier;
  final String name;

  const MultiplierTier({
    required this.minSpend,
    required this.multiplier,
    required this.name,
  });
}

const multiplierTiers = [
  MultiplierTier(minSpend: 0, multiplier: 1.0, name: 'Deckhand'),
  MultiplierTier(minSpend: 500, multiplier: 1.25, name: 'Crew'),
  MultiplierTier(minSpend: 1000, multiplier: 1.5, name: 'Bosun'),
  MultiplierTier(minSpend: 2000, multiplier: 2.0, name: 'First Mate'),
  MultiplierTier(minSpend: 5000, multiplier: 3.0, name: 'Captain'),
];

/// Get the next tier above the current spend, or null if at max.
MultiplierTier? getNextTier(double currentSpend) {
  for (final tier in multiplierTiers) {
    if (tier.minSpend > currentSpend) return tier;
  }
  return null;
}

/// Get the current tier name based on spend.
String getCurrentTierName(double monthlySpend) {
  String name = 'Deckhand';
  for (final tier in multiplierTiers) {
    if (monthlySpend >= tier.minSpend) {
      name = tier.name;
    }
  }
  return name;
}
