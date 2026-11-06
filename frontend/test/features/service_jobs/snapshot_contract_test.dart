// Contract: live updates (off by default) and the organisation boundary, from REAL
// payloads captured by scripts/capture_api_fixtures_service_jobs.py — the snapshot
// state a contractor reads, another organisation's records without names, document
// uploads and the new error codes.
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';

import 'sj_test_helpers.dart';

void main() {
  test('the owner and a live contractor read live content', () {
    expect(ServiceJob.fromJson(sjMap('job_after_upload')).snapshotState, 'live');
    final live = ServiceJob.fromJson(sjMap('job_contractor_live'));
    expect(live.snapshotState, 'live');
    expect(live.snapshotBriefId, isNull);
    expect(live.assignment!.liveUpdates, isTrue);
  });

  test('live updates off, nothing published: header only, no summary or evidence', () {
    final job = ServiceJob.fromJson(sjMap('job_contractor_no_brief'));
    expect(job.snapshotState, 'no_brief_published');
    expect(job.awaitingBrief, isTrue);
    expect(job.snapshotBriefId, isNull);
    expect(job.snapshotPublishedAt, isNull);
    expect(job.issueDescription, isNull);
    expect(job.evidence, isNull);
    expect(job.assignment!.liveUpdates, isFalse);
    expect(sjList('measurements_contractor_no_brief'), isEmpty);
  });

  test('live updates off, brief published: content as of that brief', () {
    final job = ServiceJob.fromJson(sjMap('job_contractor_brief_snapshot'));
    expect(job.snapshotState, 'brief');
    expect(job.showsBriefSnapshot, isTrue);
    expect(job.snapshotBriefId, isNotNull);
    expect(job.snapshotPublishedAt, isNotNull);
    expect(job.issueDescription, isNotNull);
  });

  test('the invitation defaults to live updates off and the preview explains it', () {
    final a = Assignment.fromJson(sjMap('assignment_invited_snapshot'));
    expect(a.liveUpdates, isFalse);
    final preview = SharingPreview.fromJson(sjMap('sharing_preview_snapshot'));
    expect(preview.liveUpdates, isFalse);
    expect(preview.liveUpdatesNote, contains('as of the brief you publish'));
    final live = SharingPreview.fromJson(sjMap('sharing_preview'));
    expect(live.liveUpdates, isTrue);
    expect(live.liveUpdatesNote, isNot(preview.liveUpdatesNote));
  });

  test("another organisation's measurements stay as evidence without their people or notes", () {
    final ms = [for (final m in sjList('measurements_other_org')) Measurement.fromJson(m)];
    final byComponent = {for (final m in ms) m.component: m};
    // Recorded by the first organisation's technician.
    final gauge = byComponent['Cable gauge']!;
    expect(gauge.recordedByOtherOrganization, isTrue);
    expect(gauge.provenance.otherOrganization, isTrue);
    expect(gauge.recordedBy, isNull);
    expect(gauge.provenance.recordedBy, isNull);
    expect(gauge.notes, isNull);
    expect(gauge.recordedByAnotherOrganization, isTrue);
    expect(gauge.confirmedByAnotherOrganization, isTrue);
    // Recorded by the owner, confirmed by the first organisation.
    final run = byComponent['Port light cable run']!;
    expect(run.provenance.recordedByRole, 'owner');
    expect(run.recordedByAnotherOrganization, isFalse);
    expect(run.confirmedByAnotherOrganization, isTrue);
    expect(run.confirmation!.confirmedBy, isNull);
    expect(run.confirmation!.confirmedAt, isNotNull);
    // The owner's own later record is untouched.
    final screws = byComponent['Light fitting screws']!;
    expect(screws.fromOtherOrganization, isFalse);
    expect(screws.recordedBy, isNotNull);
    // Owner and same-organisation views carry the flags as false.
    for (final m in sjList('measurements')) {
      expect(Measurement.fromJson(m).fromOtherOrganization, isFalse);
    }
  });

  test("another organisation's preparation confirmation keeps the time, not the person", () {
    final items = [for (final i in sjList('preparation_items_other_org')) PreparationItem.fromJson(i)];
    final confirmed = items.firstWhere((i) => i.status == 'contractor_confirmed');
    expect(confirmed.confirmedBy, isNull);
    expect(confirmed.confirmedAt, isNotNull);
    expect(confirmed.confirmedByOtherOrganization, isTrue);
    final own = PreparationItem.fromJson(sjMap('preparation_item_confirmed'));
    expect(own.confirmedByOtherOrganization, isFalse);
  });

  test('job documents: a plain PDF is accepted; active content is refused with a plain reason', () {
    final intent = AssetIntent.fromJson(sjMap('asset_pdf_intent'));
    expect(intent.asset.purpose, 'job_document');
    final ok = ServiceAsset.fromJson(sjMap('asset_pdf_processed'));
    expect(ok.status, 'available');
    expect(ok.detectedType, 'application/pdf');
    expect(ok.pages, 1);
    final bad = ServiceAsset.fromJson(sjMap('asset_pdf_rejected_processed'));
    expect(bad.status, 'rejected');
    expect(bad.rejectionReason, 'active_pdf_content');
    expect(rejectionReasonLabel(bad.rejectionReason), contains('active content'));
    for (final reason in ['pdf_metadata_unremovable', 'too_many_pages', 'encrypted_pdf', 'malformed_pdf']) {
      expect(rejectionReasonLabels.containsKey(reason), isTrue, reason: reason);
    }
  });

  test('live_updates_not_shared is a plain explanation', () {
    final e = ApiError.fromResponse(403, sj('error_live_updates_not_shared'));
    expect(e.code, 'live_updates_not_shared');
    expect(describeError(e), contains('publish a new brief'));
  });
}
