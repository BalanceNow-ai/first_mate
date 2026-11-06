// Contract: the service-jobs models parse REAL payloads captured from the local
// stack (owner, assigned contractor, outsider) and keep the evidence
// distinctions the specification requires (SJ-01…SJ-10, SJ-16…SJ-18, SJ-22).
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/features/contractors/data/contractor_models.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';

import 'sj_test_helpers.dart';

void main() {
  test('every captured fixture parses with its model', () {
    final parsers = <String, void Function(dynamic)>{
      for (final n in ['job_created', 'job_updated', 'job_context_corrected', 'job_after_upload', 'job_transitioned',
        'job_contractor_view', 'job_completed_owner', 'job_cancelled', 'job_contractor_no_brief',
        'job_contractor_brief_snapshot', 'job_contractor_live'])
        n: (d) => ServiceJob.fromJson(d),
      for (final n in ['jobs_list', 'jobs_list_final']) n: (d) => [for (final m in d) JobListItem.fromJson(m)],
      for (final n in ['next_proposal', 'next_accepted', 'next_after_upload', 'next_contractor_request'])
        n: (d) => NextEvidence.fromJson(d),
      for (final n in ['request_unavailable', 'request_answered', 'request_created', 'request_waived', 'contractor_request_created'])
        n: (d) => EvidenceRequest.fromJson(d),
      for (final n in ['requests_list', 'requests_contractor']) n: (d) => [for (final m in d) EvidenceRequest.fromJson(m)],
      for (final n in ['asset_png_intent', 'asset_jpeg_intent', 'asset_rejected_intent', 'asset_pdf_intent',
        'asset_pdf_rejected_intent'])
        n: (d) => AssetIntent.fromJson(d),
      for (final n in ['asset_png_received', 'asset_png_processed', 'asset_jpeg_received', 'asset_jpeg_processed',
        'asset_rejected_received', 'asset_rejected_processed', 'asset_pdf_received', 'asset_pdf_processed',
        'asset_pdf_rejected_received', 'asset_pdf_rejected_processed'])
        n: (d) => ServiceAsset.fromJson(d),
      for (final n in ['assets_list', 'assets_contractor']) n: (d) => AssetList.fromJson(d),
      'download_url': (d) => DownloadLink.fromJson(d),
      for (final n in ['analysis_status', 'analysis_status_empty']) n: (d) => AnalysisStatus.fromJson(d),
      for (final n in ['analysis_queued', 'analysis_run']) n: (d) => AnalysisRun.fromJson(d),
      'observations': (d) => [for (final m in d) Observation.fromJson(m)],
      'observation_note': (d) => Observation.fromJson(d),
      for (final n in ['measurement_marking', 'measurement_owner', 'measurement_revised', 'measurement_confirmed'])
        n: (d) => Measurement.fromJson(d),
      for (final n in ['measurements', 'measurements_contractor', 'measurements_contractor_no_brief',
        'measurements_other_org'])
        n: (d) => [for (final m in d) Measurement.fromJson(m)],
      for (final n in ['preparation_suggested', 'preparation_items', 'preparation_items_contractor',
        'preparation_items_other_org'])
        n: (d) => [for (final m in d) PreparationItem.fromJson(m)],
      for (final n in ['preparation_item_created', 'preparation_item_confirmed', 'preparation_item_rejected'])
        n: (d) => PreparationItem.fromJson(d),
      'preparation_item_evidence': (d) => ItemEvidenceResult.fromJson(d),
      'access_general': (d) => AccessDetails.fromJson(d, 'general'),
      'access_general_get': (d) => AccessDetails.fromJson(d, 'general'),
      'access_restricted': (d) => AccessDetails.fromJson(d, 'restricted'),
      'access_restricted_contractor': (d) => AccessDetails.fromJson(d, 'restricted'),
      for (final n in ['sharing_preview', 'sharing_preview_snapshot']) n: (d) => SharingPreview.fromJson(d),
      for (final n in ['assignment_invited', 'assignment_member_restricted', 'assignment_revoked',
        'assignment_invited_snapshot'])
        n: (d) => Assignment.fromJson(d),
      'assignments': (d) => [for (final m in d) Assignment.fromJson(m)],
      for (final n in ['brief_preview', 'brief_published', 'brief_contractor']) n: (d) => Brief.fromJson(d),
      for (final n in ['briefs', 'briefs_contractor']) n: (d) => [for (final m in d) Brief.fromJson(m)],
      'brief_ack_requested_view': (d) => BriefAckResult.fromJson(d),
      for (final n in ['scope_proposed', 'scope_change_proposed']) n: (d) => ScopeRevision.fromJson(d),
      'scopes': (d) => [for (final m in d) ScopeRevision.fromJson(m)],
      for (final n in ['scope_decision_accepted', 'scope_decision_repeat', 'scope_decision_change_requested'])
        n: (d) => ScopeDecision.fromJson(d),
      for (final n in ['visit_attended', 'visit_completed']) n: (d) => VisitResult.fromJson(d),
      'visit_contested': (d) => ContestResult.fromJson(d),
      'visits': (d) => [for (final m in d) VisitEvent.fromJson(m)],
      for (final n in ['feedback_not_eligible', 'feedback_owner_open', 'feedback_owner_draft', 'feedback_owner_submitted',
        'feedback_contractor_blind', 'feedback_contractor_revealed', 'feedback_owner_revealed', 'feedback_owner_final',
        'feedback_cancelled_ineligible'])
        n: (d) => FeedbackOverview.fromJson(d),
      'feedback_response': (d) => Review.fromJson(d),
      'feedback_report': (d) => FeedbackReport.fromJson(d),
      'directory': (d) => [for (final m in d) DirectoryEntry.fromJson(m)],
      for (final n in ['contractor_me', 'contractor_me_empty']) n: (d) => [for (final m in d) MyMembership.fromJson(m)],
      for (final n in ['contractor_inbox_invited', 'contractor_inbox_assigned', 'contractor_inbox_empty'])
        n: (d) => ContractorInbox.fromJson(d),
      'org_invitations': (d) => [for (final m in d) InvitationSummary.fromJson(m)],
      'org_members': (d) => [for (final m in d) OrgMember.fromJson(m)],
      for (final n in ['invitation_accepted', 'invitation_declined']) n: (d) => InvitationSummary.fromJson(d),
    };
    for (final e in parsers.entries) {
      expect(() => e.value(sj(e.key)), returnsNormally, reason: e.key);
    }
  });

  test('SJ-01: a job reuses the vessel context and records explicit owner corrections', () {
    final created = ServiceJob.fromJson(sjMap('job_created'));
    expect(created.status, 'draft');
    expect(created.viewer.isOwner, isTrue);
    expect(created.vesselContext!.ownerConfirmed, isFalse);
    expect(created.vesselContext!.vesselLine, 'Stabicraft 2050 Supercab 2021');
    final corrected = ServiceJob.fromJson(sjMap('job_context_corrected'));
    expect(corrected.vesselContext!.ownerConfirmed, isTrue);
    expect(corrected.vesselContext!.corrections.single['fields'], ['engine.year']);
    expect(corrected.evidenceRevision, greaterThan(created.evidenceRevision));
    expect(corrected.version, greaterThan(created.version));
  });

  test('SJ-02/03: next request carries its reason and safe alternatives; a gap is recorded', () {
    final next = NextEvidence.fromJson(sjMap('next_proposal'));
    expect(next.request, isNull);
    expect(next.proposal!.reason, isNotEmpty);
    expect(next.proposal!.options, containsAll(['take_photo', 'upload_file', 'answer_with_note', 'cannot_safely_get']));
    expect(next.proposal!.safetyNote, contains('I cannot safely get this'));
    final accepted = NextEvidence.fromJson(sjMap('next_accepted'));
    expect(accepted.request!.isOutstanding, isTrue);

    final gap = EvidenceRequest.fromJson(sjMap('request_unavailable'));
    expect(gap.status, 'unavailable');
    expect(gap.unavailableReason, 'cannot_safely_access');
    expect(unavailableReasonLabel(gap.unavailableReason), 'I cannot safely get this');
    final job = ServiceJob.fromJson(sjMap('job_transitioned'));
    expect(job.gaps!.map((g) => g.requestId), contains(gap.id));

    final fromContractor = NextEvidence.fromJson(sjMap('next_contractor_request'));
    expect(fromContractor.request!.requesterRole, 'contractor');
  });

  test('uploads move upload_pending → available with quality hints; spoofed content is rejected', () {
    final intent = AssetIntent.fromJson(sjMap('asset_png_intent'));
    expect(intent.asset.status, 'upload_pending');
    expect(intent.upload!.method, 'PUT');
    expect(intent.upload!.url, endsWith('/service-assets/${intent.asset.id}/content'));
    final done = ServiceAsset.fromJson(sjMap('asset_png_processed'));
    expect(done.isAvailable, isTrue);
    expect(done.detectedType, 'image/png');
    expect(qualityHint('framing', done.quality['framing']), 'Framing: not assessed');
    expect(qualityHint('label_legibility', done.quality['label_legibility']), 'Label legibility: not assessed');
    expect(qualityHint('blur', done.quality['blur']), 'Sharpness looks OK');
    expect(done.quality.containsKey('phash'), isFalse); // internal fingerprints stay server-side
    final rejected = ServiceAsset.fromJson(sjMap('asset_rejected_processed'));
    expect(rejected.status, 'rejected');
    expect(rejectionReasonLabel(rejected.rejectionReason), contains('not supported'));
    // Downloads are short-lived attachment links, never a stored path in the contract.
    final link = DownloadLink.fromJson(sjMap('download_url'));
    expect(link.expiresAt.difference(DateTime.now()).inMinutes, lessThanOrEqualTo(5));
    for (final a in AssetList.fromJson(sjMap('assets_list')).items) {
      expect(a.toString(), isNot(contains('storage')));
    }
  });

  test('SJ-04: 25 mm ID, 32 mm OD and the clamp range stay distinct with provenance', () {
    final all = [for (final m in sjList('measurements')) Measurement.fromJson(m)];
    final id = all.singleWhere((m) => m.dimension == 'hose_internal_diameter');
    final od = all.singleWhere((m) => m.dimension == 'hose_external_diameter' && m.isCurrent);
    expect(id.displayValue, '25 mm');
    expect(id.method, 'marking_read');
    expect(id.provenance.badge, 'owner_declared');
    expect(od.valueText, '32.5');
    expect(od.provenance.badge, 'owner_measured');
    expect(dimensionLabel(id.dimension), contains('inside'));
    expect(dimensionLabel(od.dimension), contains('outside'));
    final superseded = all.singleWhere((m) => !m.isCurrent);
    expect(superseded.state, 'superseded');
    expect(provenanceLabel(superseded.state), 'Superseded');
    final confirmed = Measurement.fromJson(sjMap('measurement_confirmed'));
    expect(confirmed.provenance.badge, 'contractor_confirmed');
    expect(confirmed.confirmation!.confirmedBy, isNotNull);
  });

  test('SJ-05/09: preparation items carry unknowns and candidates; no invented quantity', () {
    final suggested = [for (final m in sjList('preparation_suggested')) PreparationItem.fromJson(m)];
    expect(suggested, isNotEmpty);
    for (final i in suggested) {
      expect(i.status, 'suggested');
      expect(i.quantity, isNull, reason: 'the assistant never invents a quantity');
      expect(i.commercialNote, isNotEmpty);
    }
    expect(suggested.expand((i) => i.openRequirements), isNotEmpty);
    final confirmed = PreparationItem.fromJson(sjMap('preparation_item_confirmed'));
    expect(confirmed.status, 'contractor_confirmed');
    expect(confirmed.quantityBasis, isNotNull);
    final withCandidates = [for (final m in sjList('preparation_items_contractor')) PreparationItem.fromJson(m)]
        .where((i) => i.candidates.isNotEmpty);
    for (final i in withCandidates) {
      for (final c in i.candidates) {
        expect(c.priceCents, isA<int>());
        expect(c.fitmentStatus, isNotEmpty);
      }
    }
    final ev = ItemEvidenceResult.fromJson(sjMap('preparation_item_evidence'));
    expect(ev.evidenceRequest.requesterRole, 'contractor');
    expect(PreparationItem.fromJson(sjMap('preparation_item_rejected')).isActive, isFalse);
  });

  test('SJ-06: sharing preview lists sections and counts; contractor sees only granted sections', () {
    final preview = SharingPreview.fromJson(sjMap('sharing_preview'));
    expect(preview.sections.map((s) => s.section), contains('access_restricted'));
    expect(preview.sections.firstWhere((s) => s.section == 'access_restricted').note, contains('individually'));
    expect(preview.withheld, contains('invoices'));
    final contractorView = ServiceJob.fromJson(sjMap('job_contractor_view'));
    expect(contractorView.viewer.isOwner, isFalse);
    expect(contractorView.viewer.can('invoices'), isFalse);
    final forbidden = ApiError.fromResponse(403, sj('error_section_forbidden'));
    expect(forbidden.code, 'section_not_shared');
    final outsider = ApiError.fromResponse(404, sj('error_outsider_job'));
    expect(outsider.isNotFound, isTrue);
    expect([for (final m in sj('contractor_me_empty') as List) m], isEmpty);
    expect(ContractorInbox.fromJson(sjMap('contractor_inbox_empty')).isEmpty, isTrue);
  });

  test('SJ-07: revoked and per-member restricted access', () {
    expect(Assignment.fromJson(sjMap('assignment_revoked')).status, 'revoked');
    expect(Assignment.fromJson(sjMap('assignment_revoked')).isLive, isFalse);
    final a = Assignment.fromJson(sjMap('assignment_member_restricted'));
    expect(a.members.single.restrictedAccess, isTrue);
    expect(AccessDetails.fromJson(sjMap('access_restricted_contractor'), 'restricted').values['gate_code'], '4321');
    // Restricted values never appear in the general job or inbox payloads.
    expect(sj('job_contractor_view').toString(), isNot(contains('4321')));
    expect(sj('contractor_inbox_assigned').toString(), isNot(contains('4321')));
  });

  test('SJ-08: brief preview → published revision; contractor requests one more view', () {
    final preview = Brief.fromJson(sjMap('brief_preview'));
    expect(preview.isPreview, isTrue);
    expect(preview.contentDigest, hasLength(64));
    final published = Brief.fromJson(sjMap('brief_published'));
    expect(published.isPublished, isTrue);
    expect(published.contentDigest, preview.contentDigest);
    final contractor = Brief.fromJson(sjMap('brief_contractor'));
    expect(contractor.content!['limitations'], isNotEmpty);
    expect(contractor.content!['evidence']['gaps'], isNotEmpty);
    final ack = BriefAckResult.fromJson(sjMap('brief_ack_requested_view'));
    expect(ack.acknowledgement.kind, 'incomplete');
    expect(ack.evidenceRequest!.status, 'outstanding');
  });

  test('SJ-10: each scope revision has its own explicit decision bound to its digest', () {
    final scopes = [for (final m in sjList('scopes')) ScopeRevision.fromJson(m)];
    final first = scopes.firstWhere((s) => s.revisionNumber == 1);
    final change = scopes.firstWhere((s) => s.isChange);
    expect(first.decision!.decision, 'accepted');
    expect(first.decision!.revisionDigest, first.contentDigest);
    expect(change.decision!.decision, 'change_requested');
    expect(change.decision!.id, isNot(first.decision!.id));
    expect(first.estimateTotalMinor, first.estimateLines.fold<int>(0, (s, l) => s + l.amountMinor));
    expect(ScopeDecision.fromJson(sjMap('scope_decision_repeat')).id, ScopeDecision.fromJson(sjMap('scope_decision_accepted')).id);
    expect(ApiError.fromResponse(409, sj('error_digest_mismatch')).code, 'digest_mismatch');
    expect(ApiError.fromResponse(403, sj('error_owner_cannot_propose')).code, 'contractor_only');
  });

  test('SJ-16/17: feedback eligibility, blind state, no default ratings, reveal', () {
    final notYet = FeedbackOverview.fromJson(sjMap('feedback_not_eligible'));
    expect(notYet.eligible, isFalse);
    expect(ineligibleReasonLabel(notYet.ineligibleReason), contains('attended'));
    final cancelled = FeedbackOverview.fromJson(sjMap('feedback_cancelled_ineligible'));
    expect(cancelled.eligible, isFalse);
    expect(cancelled.ineligibleReason, 'cancelled_before_attendance');
    final open = FeedbackOverview.fromJson(sjMap('feedback_owner_open'));
    expect(open.eligible && open.canEdit, isTrue);
    expect(open.mine, isNull);
    expect(open.dimensions, hasLength(5));
    final draft = FeedbackOverview.fromJson(sjMap('feedback_owner_draft'));
    expect(draft.mine!.ratings['invoice_clarity_and_scope_relationship'], 'not_applicable');
    final blind = FeedbackOverview.fromJson(sjMap('feedback_contractor_blind'));
    expect(blind.theirs, isNull, reason: 'nothing about the other side before reveal');
    final submitted = FeedbackOverview.fromJson(sjMap('feedback_owner_submitted'));
    expect(submitted.mine!.status, 'submitted');
    expect(submitted.theirs, isNull);
    final revealed = FeedbackOverview.fromJson(sjMap('feedback_owner_revealed'));
    expect(revealed.window!.revealed, isTrue);
    expect(revealed.theirs!.direction, 'contractor_to_owner');
    final finalView = FeedbackOverview.fromJson(sjMap('feedback_owner_final'));
    expect(finalView.theirs!.responses.single.kind, 'response');
    expect(FeedbackReport.fromJson(sjMap('feedback_report')).category, 'factual_dispute');
  });

  test('visits open the feedback window; contesting flags the job', () {
    final attended = VisitResult.fromJson(sjMap('visit_attended'));
    expect(attended.feedbackWindowOpened, isTrue);
    expect(attended.event.actorRole, 'contractor');
    final contested = ContestResult.fromJson(sjMap('visit_contested'));
    expect(contested.jobDisputed, isTrue);
    expect(contested.caseId, isNotNull);
    expect(ServiceJob.fromJson(sjMap('job_completed_owner')).disputed, isTrue);
  });

  test('SJ-22: analysis status is honest about the provider', () {
    final s = AnalysisStatus.fromJson(sjMap('analysis_status'));
    expect(s.available, isTrue);
    expect(s.substitute, isTrue);
    final obs = [for (final m in sjList('observations')) Observation.fromJson(m)];
    expect(obs.where((o) => o.origin == 'model').every((o) => o.state == 'model_suggested'), isTrue);
    expect(obs.any((o) => o.origin == 'owner'), isTrue);
  });

  test('contractor organizations, invitations and acceptance', () {
    final me = [for (final m in sjList('contractor_me')) MyMembership.fromJson(m)];
    expect(me.every((m) => m.isAdmin), isTrue);
    final inbox = ContractorInbox.fromJson(sjMap('contractor_inbox_invited'));
    expect(inbox.invitations.single.isPending, isTrue);
    expect(inbox.invitations.single.toString(), isNot(contains('issue_description')));
    final accepted = InvitationSummary.fromJson(sjMap('invitation_accepted'));
    expect(accepted.status, 'accepted');
    expect(accepted.members, hasLength(1));
    expect(InvitationSummary.fromJson(sjMap('invitation_declined')).status, 'declined');
    final assigned = ContractorInbox.fromJson(sjMap('contractor_inbox_assigned'));
    expect(assigned.assigned.single.jobId, jobId);
    final members = [for (final m in sjList('org_members')) OrgMember.fromJson(m)];
    expect(members.map((m) => m.role), containsAll(['admin', 'member']));
  });

  test('errors carry machine codes', () {
    expect(ApiError.fromResponse(409, sj('error_version_conflict')).code, 'version_conflict');
    expect(ApiError.fromResponse(400, sj('error_idempotency_key_required')).code, 'idempotency_key_required');
    expect(ApiError.fromResponse(422, sj('error_validation_job')).errors, isNotEmpty);
    expect(ApiError.fromResponse(404, sj('error_job_not_found')).isNotFound, isTrue);
  });
}
