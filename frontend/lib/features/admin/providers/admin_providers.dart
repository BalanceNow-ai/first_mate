import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/admin.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/admin/data/admin_api.dart';
import 'package:helm_marine/features/ai_chat/data/first_mate_api.dart';

/// Review queue by verification status (`unverified` / `verified` / `rejected`).
final fitmentRulesProvider = FutureProvider.autoDispose.family<List<FitmentRule>, String>((ref, status) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).fitmentRules(status: status);
});

/// Equipment profile verification requests (`pending` / `approved` / `rejected` / `all`).
final verificationRequestsProvider =
    FutureProvider.autoDispose.family<List<VerificationRequest>, String>((ref, status) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).verificationRequests(status: status);
});

final knowledgeSourcesProvider = FutureProvider.autoDispose<List<KnowledgeSource>>((ref) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).knowledgeSources();
});

/// Knowledge domains (the First Mate's specialist keys).
final knowledgeDomainsProvider = FutureProvider.autoDispose<List<SpecialistInfo>>((ref) {
  return ref.watch(firstMateApiProvider).specialists();
});

/// Experience redemptions by status (empty string = all).
final adminRedemptionsProvider = FutureProvider.autoDispose.family<List<Redemption>, String>((ref, status) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).redemptions(status: status.isEmpty ? null : status);
});

/// Users matching an email fragment (empty = most recent).
final adminUsersProvider = FutureProvider.autoDispose.family<List<User>, String>((ref, email) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).users(email: email);
});

/// Audit trail filtered by entity type (empty = all).
final auditProvider = FutureProvider.autoDispose.family<List<AuditEntry>, String>((ref, entityType) {
  requireUserId(ref);
  return ref.watch(adminApiProvider).audit(entityType: entityType);
});
