// Contract: the invoice models parse REAL payloads captured from the local stack
// (synthetic text-layer PDF uploaded through the private-media path, read by
// the stack's local_fixture extraction substitute) and keep their meaning.
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';

import 'invoice_test_helpers.dart';

void main() {
  group('private media', () {
    test('intent → content → available, no storage paths in the contract', () {
      final intent = AssetIntent.fromJson(invMap('standalone_asset_intent'));
      expect(intent.uploadNeeded, isTrue);
      expect(intent.asset.status, 'upload_pending');
      expect(intent.asset.purpose, 'invoice');
      final accepted = ServiceAsset.fromJson(invMap('standalone_asset_content_accepted'));
      expect(accepted.isFinished, isFalse, reason: 'content is scanned/processed asynchronously');
      final available = ServiceAsset.fromJson(invMap('standalone_asset_available'));
      expect(available.isAvailable && available.isPdf, isTrue);
      expect(available.pages, 1);
      for (final name in ['standalone_asset_intent', 'standalone_asset_available', 'contractor_asset_available']) {
        final text = inv(name).toString();
        expect(text, isNot(contains('storage_key')), reason: name);
        expect(text, isNot(contains('derivative_key')), reason: name);
      }
      final job = ServiceAsset.fromJson(invMap('contractor_asset_available'));
      expect(job.purpose, 'job_document');
      expect(job.jobId, isNotNull);
      final image = ServiceAsset.fromJson(invMap('image_asset_available'));
      expect(image.isImage, isTrue);
      expect(image.width, greaterThan(0));
    });

    test('download links are short-lived signed URLs (attachment)', () {
      final link = DownloadLink.fromAssetJson(invMap('download_url_derivative'));
      expect(Uri.parse(link.url).queryParameters['X-Amz-Expires'], '300');
      expect(invMap('download_url_derivative')['disposition'], 'attachment');
      final shared = DownloadLink.fromSignedJson(invMap('contractor_shared_asset_url'));
      expect(shared.contentType, 'application/pdf');
      expect(invMap('contractor_shared_asset_url')['expires_in'], lessThanOrEqualTo(300));
    });
  });

  group('extraction', () {
    test('runs queue then finish with the substitute provider', () {
      final queued = ExtractionRun.fromJson(invMap('extraction_run_queued'));
      expect(queued.inProgress, isTrue);
      final done = ExtractionRun.fromJson(invMap('extraction_run_done'));
      expect(done.status, 'draft_ready');
      expect(done.provider, 'local_fixture');
    });

    test('every key field and line links to a page and region; low certainty needs confirmation (SJ-11)', () {
      final d = InvoiceDetail.fromJson(invMap('invoice_extracted'));
      expect(d.standalone, isTrue);
      expect(d.provisional, isTrue);
      expect(d.revision.extractionStatus, 'extracted');
      expect(d.extraction.substitute, isTrue);
      expect(d.currentRun?.status, 'draft_ready');
      expect(d.canExtract, isFalse);
      for (final name in ['supplier_name', 'invoice_number', 'invoice_date', 'currency', 'subtotal', 'tax_printed', 'total']) {
        final f = d.revision.fields[name]!;
        expect(f.page, 1, reason: name);
        expect(f.region, isNotNull, reason: name);
        expect(f.source, ValueSource.extracted, reason: name);
      }
      expect(d.revision.fields['follow_up']!.value, isNull);
      expect(d.revision.fields['follow_up']!.displaySource, ValueSource.notExtracted);
      expect(d.revision.fields['total']!.value, '458.82');
      expect(d.lines, hasLength(5));
      for (final l in d.lines) {
        expect(l.region, isNotNull);
        final r = l.region!;
        expect([r.x, r.y, r.w, r.h].every((v) => v >= 0 && v <= 1), isTrue);
      }
      final clamp = d.lines.singleWhere((l) => l.description == 'S/S hose clamp 316');
      expect(clamp.certainty, 'low');
      expect(clamp.needsConfirmation, isTrue);
      expect(clamp.quantity, '3');
      expect(d.needsConfirmation, [clamp.confirmKey]);
      final sundries = d.lines.singleWhere((l) => l.kind == 'consumable');
      expect(sundries.quantity, isNull, reason: 'missing values stay null, never filled in');
      expect(sundries.unitPrice, isNull);
      // Bank details never reach the client unmasked.
      expect(d.revision.unparsedText.map((u) => u.text).join(), isNot(contains('7890123')));
    });

    test('correction keeps the extracted value and attributes the change', () {
      final d = InvoiceDetail.fromJson(invMap('invoice_line_corrected'));
      final clamp = d.lines.singleWhere((l) => l.description == 'S/S hose clamp 316');
      expect(clamp.quantity, '4');
      expect(clamp.source, ValueSource.ownerCorrected);
      expect(clamp.correctedFields, ['quantity']);
      expect(clamp.extractedValues!['quantity'], '3');
      expect(clamp.needsConfirmation, isFalse);
      expect(d.needsConfirmation, isEmpty);
      final f = InvoiceDetail.fromJson(invMap('invoice_fields_corrected')).revision.fields['invoice_date']!;
      expect(f.value, '30 October 2026');
      expect(f.source, ValueSource.ownerCorrected);
      expect(f.extractedValue, '2026-10-30');
      expect(f.history, isNotEmpty);
    });

    test('review ends the provisional state', () {
      final d = InvoiceDetail.fromJson(invMap('invoice_reviewed'));
      expect(d.provisional, isFalse);
      expect(d.summary.status, 'owner_reviewed');
      expect(d.revision.reviewedAt, isNotNull);
    });

    test('an image the reader cannot read is honest about it (manual entry)', () {
      final d = InvoiceDetail.fromJson(invMap('invoice_image_unreadable'));
      expect(d.revision.extractionStatus, 'unreadable');
      expect(d.lines, isEmpty);
      expect(d.revision.extractionNotes, isNotEmpty);
    });

    test('manual entry has no document and refuses reading', () {
      final m = InvoiceDetail.fromJson(invMap('invoice_manual'));
      expect(m.revision.brief.origin, 'manual_entry');
      expect(m.revision.brief.sourceAssetId, isNull);
      expect(m.canExtract, isFalse);
      final added = InvoiceDetail.fromJson(invMap('invoice_manual_line_added'));
      expect(added.lines.single.source, ValueSource.ownerEntered);
      expect(added.lines.single.lineTotal, '84', reason: 'no currency stated: no minor-unit padding assumed');
      expect(InvoiceDetail.fromJson(invMap('invoice_manual_line_removed')).lines, isEmpty);
      expect(ApiError.fromResponse(409, inv('error_no_document')).code, 'no_document');
    });

    test('an invoice re-created from the same document is the same invoice', () {
      expect(InvoiceDetail.fromJson(invMap('invoice_create_existing')).id,
          InvoiceDetail.fromJson(invMap('invoice_created')).id);
      expect(InvoiceDetail.fromJson(invMap('invoice_created')).canExtract, isTrue);
    });
  });

  group('explanation', () {
    test('provisional explanation finds the arithmetic difference deterministically (SJ-12)', () {
      final e = InvoiceExplanation.fromJson(invMap('explanation_provisional'));
      expect(e.content.provisional, isTrue);
      final clampCheck = e.content.lines.singleWhere((l) => l.lineNumber == 3).arithmetic;
      expect(clampCheck.status, 'differs');
      expect(clampCheck.computed, '19.50');
      expect(clampCheck.printed, '26.00');
      expect(e.content.arithmetic.currency, 'NZD');
      expect(e.content.arithmetic.taxSource, 'printed_total');
    });

    test('standalone: comparison unavailable, no sharing question, limitations stated (SJ-15)', () {
      final e = InvoiceExplanation.fromJson(invMap('explanation_standalone'));
      final c = e.content;
      expect(c.provisional, isFalse);
      expect(c.comparison.available, isFalse);
      expect(c.comparison.reason, 'standalone_invoice');
      expect(c.lines.singleWhere((l) => l.lineNumber == 3).arithmetic.status, 'matches');
      expect(c.arithmetic.subtotal.status, 'matches');
      expect(c.arithmetic.total.status, 'differs');
      expect(c.arithmetic.total.difference, '1.00');
      expect(c.arithmetic.linesSum, '398.10');
      expect(c.obligations.single.kind, 'warranty');
      expect(c.obligations.single.page, 1);
      expect(c.suggestedQuestions.map((q) => q.key), contains('arith:total'));
      expect(c.limitations.join(' '), contains('does not judge whether prices are fair'));
      expect(c.lines.first.glossary.map((g) => g.term), contains('hr'));
      expect(InvoiceExplanation.fromJson(invMap('explanation_unchanged')).id, e.id);
      final detail = InvoiceDetail.fromJson(invMap('invoice_standalone_explained'));
      expect(detail.explanation!.stale, isFalse);
    });

    test('job-linked: matches, differences and additional work without an approval record (SJ-13)', () {
      final c = InvoiceExplanation.fromJson(invMap('explanation_job_scope')).content;
      expect(c.comparison.available, isTrue);
      final byLine = {for (final i in c.comparison.items) i.lineNumber: i};
      expect(byLine[1]!.status, 'matches');
      expect(byLine[1]!.approval!.scopeRevisionNumber, 1);
      expect(byLine[4]!.status, 'differs');
      expect(byLine[4]!.differences.map((d) => d.field), containsAll(['amount', 'unit_price']));
      expect(byLine[4]!.differences.first.approved, '85.00');
      expect(byLine[5]!.status, 'not_in_accepted_scope');
      expect(byLine[5]!.approval, isNull);
      expect(byLine[5]!.approvalText, startsWith('No approval record available'));
      expect(c.suggestedQuestions.map((q) => q.key), contains(startsWith('scope:additional')));
      final provisional = InvoiceExplanation.fromJson(invMap('explanation_job_provisional')).content;
      expect(provisional.comparison.provisional, isTrue);
    });

    test('a matched line with a missing value is "comparison unavailable", never a match', () {
      final c = InvoiceExplanation.fromJson(invMap('explanation_comparison_unavailable')).content;
      final item = c.comparison.items.single;
      expect(item.status, 'comparison_unavailable');
      expect(item.comparisonUnavailable, isTrue);
      expect(item.unavailableReasons, containsAll(['line_arithmetic_cannot_compute', 'invoice_amount_unknown']));
      expect(item.approval, isNotNull, reason: 'it is matched to a scope line, just not comparable');
      for (final r in item.unavailableReasons) {
        expect(comparisonUnavailableReasonText(r), isNot(contains('_')));
      }
      final q = c.suggestedQuestions.firstWhere((q) => q.key.startsWith('scope:unreadable:'));
      expect(q.key, 'scope:unreadable:${item.lineId}');
      expect(q.lineId, item.lineId);
      // Other comparisons carry no reasons.
      final scoped = InvoiceExplanation.fromJson(invMap('explanation_job_scope')).content;
      expect(scoped.comparison.items.every((i) => i.unavailableReasons.isEmpty), isTrue);
    });

    test('decimal strings are formatted without floating point', () {
      expect(formatInvoiceAmount('1234567.50', 'NZD'), 'NZD 1,234,567.50');
      expect(formatInvoiceAmount('-20.00', 'AUD'), 'AUD -20.00');
      expect(formatInvoiceAmount('1200', 'JPY'), 'JPY 1,200');
      expect(formatInvoiceAmount('0.1', null), '0.1');
      expect(formatInvoiceAmount(null, 'NZD'), 'Not shown');
      expect(formatInvoiceAmount('9999999999.9999', 'NZD'), 'NZD 9,999,999,999.9999');
      expect(isZeroDecimal('0.00'), isTrue);
      expect(isZeroDecimal('-0.00'), isTrue);
      expect(isZeroDecimal('0.01'), isFalse);
      expect(normaliseAmountInput(r' $1,234.50 '), '1234.50');
      expect(amountInputPattern.hasMatch('12.12345'), isFalse);
    });
  });

  group('questions', () {
    test('drafts stay private; standalone invoices cannot be shared', () {
      final q = InvoiceQuestion.fromJson(invMap('question_draft'));
      expect(q.isDraft, isTrue);
      expect(q.sharedAt, isNull);
      expect(q.origin, 'assistant_suggestion');
      final err = ApiError.fromResponse(409, inv('error_standalone_invoice'));
      expect(err.code, 'standalone_invoice');
      expect([for (final j in invList('questions_standalone')) InvoiceQuestion.fromJson(j)].single.status, 'draft');
    });

    test('an explicit send shares the chosen documents; the reply is attributed', () {
      final updated = InvoiceQuestion.fromJson(invMap('question_updated'));
      expect(updated.text, endsWith('Thanks.'));
      final sent = InvoiceQuestion.fromJson(invMap('question_sent'));
      expect(sent.status, 'shared');
      expect(sent.sharedAssetIds, hasLength(1));
      final d = InvoiceDetail.fromJson(invMap('invoice_with_response'));
      final answered = d.questions.single;
      expect(answered.status, 'answered');
      final r = answered.responses.single;
      expect(r.authorRole, 'contractor');
      expect(r.organizationId, isNotNull);
      expect(r.correctedRevisionId, d.revision.id);
      expect(d.revisions, hasLength(2));
      expect(d.revisions.first.status, 'superseded');
      expect(d.revision.brief.origin, 'contractor_correction');
      expect(d.revision.brief.supersedesId, d.revisions.first.id);
      expect(d.canExtract, isTrue, reason: 'the corrected document has not been read yet');
      expect(d.currentRun, isNull, reason: 'the latest run belongs to the superseded revision');
      expect(d.explanation, isNull, reason: 'a correction invalidates the old explanation');
      expect([for (final j in invList('questions_answered')) InvoiceQuestion.fromJson(j)].single.responses, hasLength(1));
    });

    test('the contractor sees only the sent question, its line and chosen documents', () {
      final list = [for (final j in invList('contractor_questions')) SharedInvoiceQuestion.fromJson(j)];
      final q = list.single;
      expect(q.status, 'shared');
      expect(q.line!.lineNumber, 5);
      expect(q.line!.lineTotal, '12.00');
      expect(q.sharedAssets.single.isPdf, isTrue);
      expect(inv('contractor_questions').toString(), isNot(contains('needs_confirmation')));
      final one = SharedInvoiceQuestion.fromJson(invMap('contractor_question'));
      expect(one.id, q.id);
      final responded = SharedInvoiceQuestion.fromJson(invMap('contractor_response'));
      expect(responded.status, 'answered');
      expect(responded.responses.single.correctedRevisionId, isNotNull);
    });

    test('access errors are explicit machine codes', () {
      expect(ApiError.fromResponse(404, inv('error_invoice_not_found')).isNotFound, isTrue);
      expect(ApiError.fromResponse(403, inv('error_contractor_only')).code, 'contractor_only');
      expect(ApiError.fromResponse(404, inv('error_contractor_questions_not_found')).isNotFound, isTrue);
      final conflict = ApiError.fromResponse(409, inv('error_version_conflict'));
      expect(conflict.code, 'version_conflict');
      expect(conflict.extra['current_version'], isA<int>());
      final needs = ApiError.fromResponse(409, inv('error_needs_confirmation'));
      expect(needs.code, 'needs_confirmation');
      expect(needs.extra['needs_confirmation'], isNotEmpty);
      expect(ApiError.fromResponse(409, inv('error_already_extracted')).code, 'already_extracted');
      expect(ApiError.fromResponse(400, inv('error_idempotency_key_required')).code, 'idempotency_key_required');
    });

    test('sharing a question needs the invoices section; the contractor is told plainly', () {
      final owner = ApiError.fromResponse(409, inv('error_invoices_section_not_shared'));
      expect(owner.code, 'invoices_section_not_shared');
      expect(describeError(owner), contains('Sharing tab'));
      final contractor = ApiError.fromResponse(403, inv('error_contractor_section_not_shared'));
      expect(contractor.code, 'section_not_shared');
      expect(describeError(contractor), contains('shared with you'));
      expect(describeError(const ApiError(statusCode: 409, code: 'derivative_unavailable', detail: 'x')),
          contains('Ask the owner'));
      expect(rejectionText('pdf_metadata_unremovable'), contains('metadata'));
    });
  });

  test('lists', () {
    final list = [for (final j in invList('invoice_list')) InvoiceSummary.fromJson(j)];
    expect(list.length, greaterThanOrEqualTo(2));
    expect(list.where((i) => i.standalone), isNotEmpty);
    expect(list.where((i) => !i.standalone), isNotEmpty);
    expect(list.any((i) => i.status == 'deleted'), isFalse, reason: 'deleted invoices are not listed');
    final forJob = [for (final j in invList('invoice_list_for_job')) InvoiceSummary.fromJson(j)];
    expect(forJob.single.jobId, isNotNull);
    expect(inv('invoice_list_empty'), isEmpty);
  });
}
