// Contract: admin curation models parse REAL admin payloads captured from the local stack.
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/admin.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/models/user.dart';

import '../content/engagement_test_helpers.dart';

void main() {
  test('fitment rules: queue, verified, rejected', () {
    final queue = [for (final j in engList('admin_fitment_rules_unverified')) FitmentRule.fromJson(j)];
    expect(queue, hasLength(2));
    expect(queue.every((r) => r.verificationStatus == 'unverified'), isTrue);
    expect(queue.first.confidenceScore, 0.3);
    expect(queue.first.scope.single, startsWith('Engine: Fixturesynth FX-'));
    final verified = FitmentRule.fromJson(engMap('admin_fitment_rule_verified'));
    expect(verified.verificationStatus, 'verified');
    expect(verified.confidenceScore, 0.8);
    expect(verified.verifiedBy, isNotNull);
    expect(verified.verifiedAt, isNotNull);
    expect(FitmentRule.fromJson(engMap('admin_fitment_rule_rejected')).verificationStatus, 'rejected');
    final low = ApiError.fromResponse(422, engMap('error_confidence_too_low'));
    expect(low.code, 'confidence_too_low');
    expect(low.detail, contains('0.7'));
  });

  test('equipment verification queue and review results', () {
    final queue = [for (final j in engList('admin_verification_requests')) VerificationRequest.fromJson(j)];
    expect(queue, isNotEmpty);
    final withEquipment = queue.firstWhere((r) => r.equipment.isNotEmpty);
    expect(withEquipment.vesselLabel, isNotNull);
    expect(withEquipment.equipment.first.categoryName, isNotEmpty);
    expect(VerificationRequest.fromJson(engMap('admin_verification_approved')).status, 'approved');
    final rejected = VerificationRequest.fromJson(engMap('admin_verification_rejected'));
    expect(rejected.status, 'rejected');
    expect(rejected.reviewNote, 'Serial plate photo unreadable');
  });

  test('knowledge sources: list, ingest, unchanged, admit, re-embed, revoke', () {
    final list = [for (final j in engList('admin_knowledge_sources')) KnowledgeSource.fromJson(j)];
    expect(list, isNotEmpty);
    final ingested = KnowledgeIngestResult.fromJson(engMap('admin_knowledge_ingested'));
    expect(ingested.status, 'created');
    expect(ingested.source.admissionStatus, 'pending');
    expect(ingested.source.isSynthetic, isTrue);
    expect(ingested.source.licenceVerified, isFalse);
    expect(ingested.source.chunkCount, greaterThan(0));
    expect(KnowledgeIngestResult.fromJson(engMap('admin_knowledge_ingest_unchanged')).status, 'unchanged');
    final admitted = KnowledgeSource.fromJson(engMap('admin_knowledge_admitted'));
    expect(admitted.admissionStatus, 'admitted');
    expect(admitted.canRevoke, isTrue);
    final reembedded = KnowledgeReembedResult.fromJson(engMap('admin_knowledge_reembedded'));
    expect(reembedded.chunksEmbedded, reembedded.source.chunkCount);
    expect(reembedded.source.embeddingModels, isNotEmpty);
    expect(KnowledgeSource.fromJson(engMap('admin_knowledge_revoked')).admissionStatus, 'revoked');
    expect(ApiError.fromResponse(409, engMap('error_licence_not_verified')).code, 'licence_not_verified');
  });

  test('ingest draft uses the server field names', () {
    const draft = KnowledgeIngestDraft(
      title: 'T',
      licence: 'CC BY 4.0',
      domain: 'engine',
      content: '# x',
      licenceVerified: true,
      isSynthetic: true,
    );
    expect(draft.toJson().keys, containsAll(['title', 'licence', 'licence_verified', 'domain', 'is_synthetic', 'format', 'content']));
  });

  test('admin redemptions lifecycle', () {
    final queue = [for (final j in engList('admin_redemptions')) Redemption.fromJson(j)];
    expect(queue.every((r) => r.userId != null && r.status == 'requested'), isTrue);
    final confirmed = Redemption.fromJson(engMap('admin_redemption_confirmed'));
    expect(confirmed.status, 'confirmed');
    expect(confirmed.staffNote, 'Booked for Saturday');
    expect(confirmed.canFulfil, isTrue);
    final fulfilled = Redemption.fromJson(engMap('admin_redemption_fulfilled'));
    expect(fulfilled.fulfilledAt, isNotNull);
    expect(fulfilled.canCancel, isFalse);
    expect(Redemption.fromJson(engMap('admin_redemption_cancelled')).status, 'cancelled');
    expect(ApiError.fromResponse(409, engMap('error_invalid_transition')).code, 'invalid_transition');
  });

  test('users, role change, audit and forbidden', () {
    final users = [for (final j in engList('admin_users')) User.fromJson(j)];
    expect(users.map((u) => u.role), contains('admin'));
    expect(User.fromJson(engMap('admin_user_role_updated')).role, 'operator');
    final audit = [for (final j in engList('admin_audit')) AuditEntry.fromJson(j)];
    expect(audit.first.action, 'set_role');
    expect(audit.first.detail, {'to': 'customer', 'from': 'operator'});
    final forbidden = ApiError.fromResponse(403, engMap('error_forbidden'));
    expect(forbidden.code, 'forbidden');
    expect(describeError(ApiError.fromResponse(422, engMap('error_validation_role'))), contains('role'));
  });
}
