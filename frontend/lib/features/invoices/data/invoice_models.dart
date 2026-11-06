// Typed models for "Understand my invoice" (`/invoices`, `/service-assets`,
// `/service-jobs/{id}/invoice-questions`).
//
// Money and quantities are exact decimal STRINGS in the invoice's stated
// currency (e.g. "237.50", "-20.00", "1200" for JPY). They are carried as
// strings end to end and only formatted for display (see invoice_amount.dart);
// the server does every calculation. `null` means "not printed / not known" and
// is never filled in.
import 'package:helm_marine/core/models/json.dart';

String? _optString(Map<String, dynamic> json, String key) => opt<String>(json, key);

/// A normalised page box (0–1 from the top-left corner).
class InvoiceRegion {
  const InvoiceRegion({required this.x, required this.y, required this.w, required this.h});

  final double x;
  final double y;
  final double w;
  final double h;

  static InvoiceRegion? fromJson(Map<String, dynamic>? json) {
    if (json == null) return null;
    double n(String k) => (req<num>(json, k)).toDouble();
    return InvoiceRegion(x: n('x'), y: n('y'), w: n('w'), h: n('h'));
  }

  /// "page 1, about 15% down" — a text alternative for the highlight.
  String describe(int? page) {
    final down = (y * 100).round();
    return '${page == null ? 'Page unknown' : 'Page $page'}, about $down% down the page';
  }
}

/// Where a value came from.
enum ValueSource {
  extracted('Read from the document'),
  ownerCorrected('You corrected this'),
  ownerConfirmed('You confirmed this as printed'),
  ownerEntered('You entered this'),
  notExtracted('Not found on the document');

  const ValueSource(this.label);

  final String label;

  static ValueSource parse(String wire) => switch (wire) {
        'extracted' => ValueSource.extracted,
        'owner_corrected' => ValueSource.ownerCorrected,
        'owner_confirmed' => ValueSource.ownerConfirmed,
        'owner_entered' => ValueSource.ownerEntered,
        'not_extracted' => ValueSource.notExtracted,
        _ => throw FormatException('Unknown value source "$wire"'),
      };
}

/// Header fields in display order, with plain-English labels.
const invoiceFieldLabels = <String, String>{
  'supplier_name': 'Supplier',
  'invoice_number': 'Invoice number',
  'invoice_date': 'Invoice date',
  'currency': 'Currency',
  'subtotal': 'Subtotal',
  'tax_printed': 'Tax (as printed)',
  'total': 'Total',
  'warranty': 'Warranty',
  'follow_up': 'Follow-up or next service',
};

const invoiceAmountFields = {'subtotal', 'tax_printed', 'total'};

class FieldHistoryEntry {
  const FieldHistoryEntry({this.value, this.source, this.at});

  final String? value;
  final String? source;
  final String? at;

  factory FieldHistoryEntry.fromJson(Map<String, dynamic> json) => FieldHistoryEntry(
        value: _optString(json, 'value'),
        source: _optString(json, 'source'),
        at: _optString(json, 'at'),
      );
}

class InvoiceField {
  const InvoiceField({
    required this.name,
    required this.value,
    required this.source,
    required this.certainty,
    required this.page,
    required this.region,
    required this.illegible,
    required this.needsConfirmation,
    required this.extractedValue,
    required this.at,
    required this.history,
  });

  final String name;
  final String? value;
  final ValueSource source;

  /// high | medium | low | unknown
  final String certainty;
  final int? page;
  final InvoiceRegion? region;
  final bool illegible;
  final bool needsConfirmation;
  final String? extractedValue;
  final String? at;
  final List<FieldHistoryEntry> history;

  String get label => invoiceFieldLabels[name] ?? name;
  bool get isAmount => invoiceAmountFields.contains(name);

  /// True when the shown value differs from what was read off the document.
  bool get differsFromExtracted => source == ValueSource.ownerCorrected;

  /// What to show as the source: a field the reader found nothing for reads
  /// "Not found on the document" rather than "Read from the document".
  ValueSource get displaySource =>
      source == ValueSource.extracted && value == null && !illegible ? ValueSource.notExtracted : source;

  factory InvoiceField.fromJson(Map<String, dynamic> json) => InvoiceField(
        name: req<String>(json, 'name'),
        value: _optString(json, 'value'),
        source: ValueSource.parse(req<String>(json, 'source')),
        certainty: req<String>(json, 'certainty'),
        page: opt<int>(json, 'page'),
        region: InvoiceRegion.fromJson(optMap(json, 'region')),
        illegible: req<bool>(json, 'illegible'),
        needsConfirmation: req<bool>(json, 'needs_confirmation'),
        extractedValue: _optString(json, 'extracted_value'),
        at: _optString(json, 'at'),
        history: [for (final h in mapList(json, 'history')) FieldHistoryEntry.fromJson(h)],
      );
}

/// Line kinds with plain labels (the wire values are the server's vocabulary).
const lineKindLabels = <String, String>{
  'part': 'Part or material',
  'labour': 'Labour',
  'travel': 'Travel',
  'call_out': 'Call-out',
  'consumable': 'Consumables',
  'discount': 'Discount',
  'fee': 'Fee or levy',
  'tax': 'Tax',
  'other': 'Other',
  'unknown': 'Not categorised',
};

const lineValueLabels = <String, String>{
  'kind': 'Type',
  'description': 'Description',
  'part_number': 'Part number',
  'quantity': 'Quantity',
  'unit': 'Unit',
  'unit_price': 'Unit price',
  'line_total': 'Line amount',
  'tax_printed': 'Tax on line',
  'currency': 'Currency',
};

class InvoiceLine {
  const InvoiceLine({
    required this.id,
    required this.lineNumber,
    required this.kind,
    required this.description,
    required this.partNumber,
    required this.quantity,
    required this.unit,
    required this.unitPrice,
    required this.lineTotal,
    required this.taxPrinted,
    required this.currency,
    required this.page,
    required this.region,
    required this.certainty,
    required this.source,
    required this.needsConfirmation,
    required this.illegible,
    required this.extractedValues,
    required this.correctedFields,
    required this.version,
  });

  final String id;
  final int lineNumber;
  final String kind;
  final String? description;
  final String? partNumber;
  final String? quantity;
  final String? unit;
  final String? unitPrice;
  final String? lineTotal;
  final String? taxPrinted;
  final String? currency;
  final int? page;
  final InvoiceRegion? region;
  final String certainty;
  final ValueSource source;
  final bool needsConfirmation;
  final List<String> illegible;

  /// The values as originally read off the document (null for a line you added).
  final Map<String, String?>? extractedValues;
  final List<String> correctedFields;
  final int version;

  String get kindLabel => lineKindLabels[kind] ?? kind;
  String get confirmKey => 'line:$id';

  /// The current value of a line column by its wire name.
  String? valueOf(String column) => switch (column) {
        'kind' => kind,
        'description' => description,
        'part_number' => partNumber,
        'quantity' => quantity,
        'unit' => unit,
        'unit_price' => unitPrice,
        'line_total' => lineTotal,
        'tax_printed' => taxPrinted,
        'currency' => currency,
        _ => null,
      };

  factory InvoiceLine.fromJson(Map<String, dynamic> json) {
    final extracted = optMap(json, 'extracted_values');
    return InvoiceLine(
      id: req<String>(json, 'id'),
      lineNumber: req<int>(json, 'line_number'),
      kind: req<String>(json, 'kind'),
      description: _optString(json, 'description'),
      partNumber: _optString(json, 'part_number'),
      quantity: _optString(json, 'quantity'),
      unit: _optString(json, 'unit'),
      unitPrice: _optString(json, 'unit_price'),
      lineTotal: _optString(json, 'line_total'),
      taxPrinted: _optString(json, 'tax_printed'),
      currency: _optString(json, 'currency'),
      page: opt<int>(json, 'page'),
      region: InvoiceRegion.fromJson(optMap(json, 'region')),
      certainty: req<String>(json, 'certainty'),
      source: ValueSource.parse(req<String>(json, 'source')),
      needsConfirmation: req<bool>(json, 'needs_confirmation'),
      illegible: stringList(json, 'illegible'),
      extractedValues: extracted == null ? null : {for (final e in extracted.entries) e.key: e.value as String?},
      correctedFields: stringList(json, 'corrected_fields'),
      version: req<int>(json, 'version'),
    );
  }
}

class UnparsedText {
  const UnparsedText({required this.text, required this.page, required this.region});

  final String? text;
  final int? page;
  final InvoiceRegion? region;

  factory UnparsedText.fromJson(Map<String, dynamic> json) => UnparsedText(
        text: _optString(json, 'text'),
        page: opt<int>(json, 'page'),
        region: InvoiceRegion.fromJson(optMap(json, 'region')),
      );
}

class InvoiceRevisionBrief {
  const InvoiceRevisionBrief({
    required this.id,
    required this.revisionNumber,
    required this.origin,
    required this.status,
    required this.sourceAssetId,
    required this.uploadedBy,
    required this.organizationId,
    required this.supersedesId,
    required this.createdAt,
  });

  final String id;
  final int revisionNumber;

  /// owner_upload | contractor_correction | manual_entry
  final String origin;

  /// uploaded | extraction_draft | owner_reviewed | superseded
  final String status;
  final String? sourceAssetId;
  final String uploadedBy;
  final String? organizationId;
  final String? supersedesId;
  final DateTime createdAt;

  String get originLabel => switch (origin) {
        'owner_upload' => 'Uploaded by you',
        'contractor_correction' => 'Corrected invoice from the contractor',
        'manual_entry' => 'Entered by hand',
        _ => origin,
      };

  factory InvoiceRevisionBrief.fromJson(Map<String, dynamic> json) => InvoiceRevisionBrief(
        id: req<String>(json, 'id'),
        revisionNumber: req<int>(json, 'revision_number'),
        origin: req<String>(json, 'origin'),
        status: req<String>(json, 'status'),
        sourceAssetId: _optString(json, 'source_asset_id'),
        uploadedBy: req<String>(json, 'uploaded_by'),
        organizationId: _optString(json, 'organization_id'),
        supersedesId: _optString(json, 'supersedes_id'),
        createdAt: reqDate(json, 'created_at'),
      );
}

class InvoiceRevision {
  const InvoiceRevision({
    required this.brief,
    required this.currency,
    required this.rounding,
    required this.version,
    required this.extractionStatus,
    required this.extractionProvider,
    required this.extractionNotes,
    required this.unparsedText,
    required this.reviewedAt,
    required this.fields,
  });

  final InvoiceRevisionBrief brief;
  final String? currency;
  final String rounding;
  final int version;

  /// none | extracted | unreadable
  final String extractionStatus;
  final String? extractionProvider;
  final List<String> extractionNotes;
  final List<UnparsedText> unparsedText;
  final String? reviewedAt;
  final Map<String, InvoiceField> fields;

  String get id => brief.id;

  /// Fields in display order.
  List<InvoiceField> get orderedFields => [
        for (final name in invoiceFieldLabels.keys)
          if (fields[name] != null) fields[name]!,
      ];

  factory InvoiceRevision.fromJson(Map<String, dynamic> json) {
    final fields = reqMap(json, 'fields');
    return InvoiceRevision(
      brief: InvoiceRevisionBrief.fromJson(json),
      currency: _optString(json, 'currency'),
      rounding: req<String>(json, 'rounding'),
      version: req<int>(json, 'version'),
      extractionStatus: req<String>(json, 'extraction_status'),
      extractionProvider: _optString(json, 'extraction_provider'),
      extractionNotes: stringList(json, 'extraction_notes'),
      unparsedText: [for (final u in mapList(json, 'unparsed_text')) UnparsedText.fromJson(u)],
      reviewedAt: _optString(json, 'reviewed_at'),
      fields: {
        for (final e in fields.entries) e.key: InvoiceField.fromJson((e.value as Map).cast<String, dynamic>()),
      },
    );
  }
}

class ExtractionRun {
  const ExtractionRun({
    required this.id,
    required this.status,
    required this.invoiceRevisionId,
    required this.provider,
    required this.attempts,
    required this.error,
    required this.staleReason,
  });

  final String id;

  /// pending | running | draft_ready | confirmed | superseded | failed | cancelled
  final String status;
  final String? invoiceRevisionId;
  final String? provider;
  final int attempts;
  final String? error;
  final String? staleReason;

  bool get inProgress => status == 'pending' || status == 'running';
  bool get failed => status == 'failed' || status == 'cancelled';

  factory ExtractionRun.fromJson(Map<String, dynamic> json) => ExtractionRun(
        id: req<String>(json, 'id'),
        status: req<String>(json, 'status'),
        invoiceRevisionId: _optString(json, 'invoice_revision_id'),
        provider: _optString(json, 'provider'),
        attempts: req<int>(json, 'attempts'),
        error: _optString(json, 'error'),
        staleReason: _optString(json, 'stale_reason'),
      );
}

class ExtractionStatus {
  const ExtractionStatus({
    required this.provider,
    required this.available,
    required this.message,
    required this.substitute,
    required this.latestRun,
  });

  final String provider;
  final bool available;
  final String? message;

  /// The development/test reader (proves the flow, not reading accuracy).
  final bool substitute;
  final ExtractionRun? latestRun;

  factory ExtractionStatus.fromJson(Map<String, dynamic> json) {
    final run = optMap(json, 'latest_run');
    return ExtractionStatus(
      provider: req<String>(json, 'provider'),
      available: req<bool>(json, 'available'),
      message: _optString(json, 'message'),
      substitute: req<bool>(json, 'substitute'),
      latestRun: run == null ? null : ExtractionRun.fromJson(run),
    );
  }
}

// ----------------------------------------------------------------- explanation
class GlossaryTerm {
  const GlossaryTerm(this.term, this.meaning);

  final String term;
  final String meaning;

  factory GlossaryTerm.fromJson(Map<String, dynamic> json) =>
      GlossaryTerm(req<String>(json, 'term'), req<String>(json, 'meaning'));
}

/// quantity × unit price versus the printed line amount.
class LineCheck {
  const LineCheck({
    required this.computed,
    required this.printed,
    required this.difference,
    required this.amountUsed,
    required this.status,
    required this.reasons,
    required this.notes,
  });

  final String? computed;
  final String? printed;
  final String? difference;
  final String? amountUsed;

  /// matches | differs | printed_only | computed_only | cannot_compute
  final String status;
  final List<String> reasons;
  final List<String> notes;

  factory LineCheck.fromJson(Map<String, dynamic> json) => LineCheck(
        computed: _optString(json, 'computed'),
        printed: _optString(json, 'printed'),
        difference: _optString(json, 'difference'),
        amountUsed: _optString(json, 'amount_used'),
        status: req<String>(json, 'status'),
        reasons: stringList(json, 'reasons'),
        notes: stringList(json, 'notes'),
      );
}

/// A printed subtotal/total compared with the deterministic sum.
class TotalCheck {
  const TotalCheck({
    required this.printed,
    required this.computed,
    required this.difference,
    required this.status,
    required this.reasons,
    required this.notes,
  });

  final String? printed;
  final String? computed;
  final String? difference;

  /// matches | differs | not_printed | cannot_compute
  final String status;
  final List<String> reasons;
  final List<String> notes;

  factory TotalCheck.fromJson(Map<String, dynamic> json) => TotalCheck(
        printed: _optString(json, 'printed'),
        computed: _optString(json, 'computed'),
        difference: _optString(json, 'difference'),
        status: req<String>(json, 'status'),
        reasons: stringList(json, 'reasons'),
        notes: stringList(json, 'notes'),
      );
}

class ArithmeticChecks {
  const ArithmeticChecks({
    required this.currency,
    required this.currencyStatus,
    required this.lineCurrencies,
    required this.status,
    required this.blockers,
    required this.linesSum,
    required this.taxPrinted,
    required this.taxSource,
    required this.taxNote,
    required this.subtotal,
    required this.total,
    required this.roundingPolicyText,
  });

  final String? currency;

  /// stated | stated_on_lines | missing | mixed | unrecognised
  final String currencyStatus;
  final List<String> lineCurrencies;

  /// complete | cannot_compute
  final String status;
  final List<String> blockers;
  final String? linesSum;
  final String? taxPrinted;

  /// printed_total | tax_lines | not_printed | unreadable
  final String taxSource;
  final String? taxNote;
  final TotalCheck subtotal;
  final TotalCheck total;
  final String? roundingPolicyText;

  factory ArithmeticChecks.fromJson(Map<String, dynamic> json) {
    final tax = reqMap(json, 'tax');
    return ArithmeticChecks(
      currency: _optString(json, 'currency'),
      currencyStatus: req<String>(json, 'currency_status'),
      lineCurrencies: stringList(json, 'line_currencies'),
      status: req<String>(json, 'status'),
      blockers: [for (final b in (json['blockers'] as List? ?? const [])) '$b'],
      linesSum: _optString(json, 'lines_sum'),
      taxPrinted: _optString(tax, 'printed'),
      taxSource: req<String>(tax, 'source'),
      taxNote: _optString(tax, 'note'),
      subtotal: TotalCheck.fromJson(reqMap(json, 'subtotal_check')),
      total: TotalCheck.fromJson(reqMap(json, 'total_check')),
      roundingPolicyText: _optString(json, 'rounding_policy_text'),
    );
  }
}

class RelatedItem {
  const RelatedItem({required this.type, required this.name, required this.status});

  /// preparation_item | reported_problem
  final String type;
  final String? name;
  final String? status;

  factory RelatedItem.fromJson(Map<String, dynamic> json) => RelatedItem(
        type: req<String>(json, 'type'),
        name: _optString(json, 'name'),
        status: _optString(json, 'status'),
      );
}

class ExplainedLine {
  const ExplainedLine({
    required this.lineId,
    required this.lineNumber,
    required this.kind,
    required this.plainLanguage,
    required this.glossary,
    required this.arithmetic,
    required this.relatedToJob,
    required this.page,
    required this.region,
    required this.certainty,
    required this.needsConfirmation,
  });

  final String lineId;
  final int lineNumber;
  final String kind;
  final String plainLanguage;
  final List<GlossaryTerm> glossary;
  final LineCheck arithmetic;
  final List<RelatedItem> relatedToJob;
  final int? page;
  final InvoiceRegion? region;
  final String? certainty;
  final bool needsConfirmation;

  factory ExplainedLine.fromJson(Map<String, dynamic> json) {
    final source = optMap(json, 'source') ?? const <String, dynamic>{};
    return ExplainedLine(
      lineId: req<String>(json, 'line_id'),
      lineNumber: req<int>(json, 'line_number'),
      kind: req<String>(json, 'kind'),
      plainLanguage: req<String>(json, 'plain_language'),
      glossary: [for (final g in mapList(json, 'glossary')) GlossaryTerm.fromJson(g)],
      arithmetic: LineCheck.fromJson(reqMap(json, 'arithmetic')),
      relatedToJob: [for (final r in mapList(json, 'related_to_job')) RelatedItem.fromJson(r)],
      page: opt<int>(source, 'page'),
      region: InvoiceRegion.fromJson(optMap(source, 'region')),
      certainty: _optString(json, 'certainty'),
      needsConfirmation: opt<bool>(json, 'needs_confirmation') ?? false,
    );
  }
}

class ScopeDifference {
  const ScopeDifference({required this.field, required this.invoice, required this.approved});

  final String field;
  final String? invoice;
  final String? approved;

  String get label => switch (field) {
        'amount' => 'Amount',
        'unit_price' => 'Unit price',
        'quantity' => 'Quantity',
        'currency' => 'Currency',
        _ => field,
      };

  factory ScopeDifference.fromJson(Map<String, dynamic> json) => ScopeDifference(
        field: req<String>(json, 'field'),
        invoice: _optString(json, 'invoice'),
        approved: _optString(json, 'approved'),
      );
}

/// The explicit owner decision a matched line relates to.
class ApprovalRecord {
  const ApprovalRecord({
    required this.scopeRevisionNumber,
    required this.isChange,
    required this.decisionId,
    required this.decidedAt,
    required this.scopeLineDescription,
  });

  final int scopeRevisionNumber;
  final bool isChange;
  final String decisionId;
  final String decidedAt;
  final String? scopeLineDescription;

  factory ApprovalRecord.fromJson(Map<String, dynamic> json) => ApprovalRecord(
        scopeRevisionNumber: req<int>(json, 'scope_revision_number'),
        isChange: req<bool>(json, 'is_change'),
        decisionId: req<String>(json, 'decision_id'),
        decidedAt: req<String>(json, 'decided_at'),
        scopeLineDescription: _optString(json, 'scope_line_description'),
      );
}

class ComparisonItem {
  const ComparisonItem({
    required this.lineId,
    required this.lineNumber,
    required this.description,
    required this.status,
    required this.additionalWork,
    required this.differences,
    required this.approval,
    required this.approvalText,
    this.unavailableReasons = const [],
  });

  final String lineId;
  final int lineNumber;
  final String? description;

  /// matches | differs | comparison_unavailable | not_in_accepted_scope | not_compared
  final String status;

  /// Why a matched line can't be compared (status `comparison_unavailable`): a value
  /// is missing or unreadable — never treated as a match.
  final List<String> unavailableReasons;

  bool get comparisonUnavailable => status == 'comparison_unavailable';
  final bool additionalWork;
  final List<ScopeDifference> differences;
  final ApprovalRecord? approval;
  final String? approvalText;

  factory ComparisonItem.fromJson(Map<String, dynamic> json) {
    final approval = optMap(json, 'approval');
    return ComparisonItem(
      lineId: req<String>(json, 'line_id'),
      lineNumber: req<int>(json, 'line_number'),
      description: _optString(json, 'description'),
      status: req<String>(json, 'status'),
      unavailableReasons: json['unavailable_reasons'] == null ? const [] : stringList(json, 'unavailable_reasons'),
      additionalWork: opt<bool>(json, 'additional_work') ?? false,
      differences: [for (final d in mapList(json, 'differences')) ScopeDifference.fromJson(d)],
      approval: approval == null ? null : ApprovalRecord.fromJson(approval),
      approvalText: _optString(json, 'approval_text'),
    );
  }
}

class NotInvoicedScopeLine {
  const NotInvoicedScopeLine({required this.scopeRevisionNumber, required this.description, required this.amount});

  final int scopeRevisionNumber;
  final String? description;
  final String? amount;

  factory NotInvoicedScopeLine.fromJson(Map<String, dynamic> json) => NotInvoicedScopeLine(
        scopeRevisionNumber: req<int>(json, 'scope_revision_number'),
        description: _optString(json, 'description'),
        amount: _optString(json, 'amount'),
      );
}

class ScopeComparison {
  const ScopeComparison({
    required this.status,
    required this.reason,
    required this.message,
    required this.provisional,
    required this.items,
    required this.notInvoiced,
  });

  /// available | unavailable
  final String status;

  /// standalone_invoice | no_accepted_scope (when unavailable)
  final String? reason;
  final String? message;
  final bool provisional;
  final List<ComparisonItem> items;
  final List<NotInvoicedScopeLine> notInvoiced;

  bool get available => status == 'available';

  factory ScopeComparison.fromJson(Map<String, dynamic> json) => ScopeComparison(
        status: req<String>(json, 'status'),
        reason: _optString(json, 'reason'),
        message: _optString(json, 'message'),
        provisional: opt<bool>(json, 'provisional') ?? false,
        items: [for (final i in mapList(json, 'items')) ComparisonItem.fromJson(i)],
        notInvoiced: [
          for (final n in (json['scope_lines_not_invoiced'] as List? ?? const []))
            NotInvoicedScopeLine.fromJson((n as Map).cast<String, dynamic>()),
        ],
      );
}

class PossibleDuplicate {
  const PossibleDuplicate({required this.lineIds, required this.lineNumbers, required this.note});

  final List<String> lineIds;
  final List<int> lineNumbers;
  final String note;

  factory PossibleDuplicate.fromJson(Map<String, dynamic> json) => PossibleDuplicate(
        lineIds: stringList(json, 'line_ids'),
        lineNumbers: [for (final n in json['line_numbers'] as List) n as int],
        note: req<String>(json, 'note'),
      );
}

class Obligation {
  const Obligation({
    required this.kind,
    required this.text,
    required this.note,
    required this.sourceField,
    required this.sourceLineNumber,
    required this.page,
    required this.region,
  });

  /// warranty | follow_up
  final String kind;
  final String text;
  final String? note;
  final String? sourceField;
  final int? sourceLineNumber;
  final int? page;
  final InvoiceRegion? region;

  String get sourceLabel {
    final where = sourceField != null
        ? (invoiceFieldLabels[sourceField] ?? sourceField!)
        : (sourceLineNumber != null ? 'Line $sourceLineNumber' : 'The invoice');
    return page == null ? where : '$where, page $page';
  }

  factory Obligation.fromJson(Map<String, dynamic> json) {
    final source = optMap(json, 'source') ?? const <String, dynamic>{};
    return Obligation(
      kind: req<String>(json, 'kind'),
      text: req<String>(json, 'text'),
      note: _optString(json, 'note'),
      sourceField: _optString(source, 'field'),
      sourceLineNumber: opt<int>(source, 'line_number'),
      page: opt<int>(source, 'page'),
      region: InvoiceRegion.fromJson(optMap(source, 'region')),
    );
  }
}

class SuggestedQuestion {
  const SuggestedQuestion({required this.key, required this.lineId, required this.text});

  final String key;
  final String? lineId;
  final String text;

  factory SuggestedQuestion.fromJson(Map<String, dynamic> json) => SuggestedQuestion(
        key: req<String>(json, 'key'),
        lineId: _optString(json, 'line_id'),
        text: req<String>(json, 'text'),
      );
}

class ExplanationContent {
  const ExplanationContent({
    required this.revisionNumber,
    required this.provisional,
    required this.needsConfirmation,
    required this.currencyCode,
    required this.currencyStatus,
    required this.roundingPolicy,
    required this.lines,
    required this.arithmetic,
    required this.comparison,
    required this.duplicates,
    required this.obligations,
    required this.suggestedQuestions,
    required this.limitations,
  });

  final int revisionNumber;
  final bool provisional;
  final List<String> needsConfirmation;
  final String? currencyCode;
  final String currencyStatus;
  final String? roundingPolicy;
  final List<ExplainedLine> lines;
  final ArithmeticChecks arithmetic;
  final ScopeComparison comparison;
  final List<PossibleDuplicate> duplicates;
  final List<Obligation> obligations;
  final List<SuggestedQuestion> suggestedQuestions;
  final List<String> limitations;

  factory ExplanationContent.fromJson(Map<String, dynamic> json) {
    final currency = reqMap(json, 'currency');
    return ExplanationContent(
      revisionNumber: req<int>(json, 'revision_number'),
      provisional: req<bool>(json, 'provisional'),
      needsConfirmation: stringList(json, 'needs_confirmation'),
      currencyCode: _optString(currency, 'code'),
      currencyStatus: req<String>(currency, 'status'),
      roundingPolicy: _optString(json, 'rounding_policy'),
      lines: [for (final l in mapList(json, 'lines')) ExplainedLine.fromJson(l)],
      arithmetic: ArithmeticChecks.fromJson(reqMap(json, 'arithmetic')),
      comparison: ScopeComparison.fromJson(reqMap(json, 'comparison')),
      duplicates: [for (final d in mapList(json, 'duplicates')) PossibleDuplicate.fromJson(d)],
      obligations: [for (final o in mapList(json, 'obligations')) Obligation.fromJson(o)],
      suggestedQuestions: [for (final q in mapList(json, 'suggested_questions')) SuggestedQuestion.fromJson(q)],
      limitations: stringList(json, 'limitations'),
    );
  }
}

class InvoiceExplanation {
  const InvoiceExplanation({
    required this.id,
    required this.revisionId,
    required this.status,
    required this.stale,
    required this.createdAt,
    required this.content,
  });

  final String id;
  final String revisionId;

  /// current | superseded
  final String status;

  /// The invoice changed since this was written (refresh it).
  final bool stale;
  final DateTime createdAt;
  final ExplanationContent content;

  factory InvoiceExplanation.fromJson(Map<String, dynamic> json) => InvoiceExplanation(
        id: req<String>(json, 'id'),
        revisionId: req<String>(json, 'invoice_revision_id'),
        status: req<String>(json, 'status'),
        stale: req<bool>(json, 'stale'),
        createdAt: reqDate(json, 'created_at'),
        content: ExplanationContent.fromJson(reqMap(json, 'content')),
      );
}

// ------------------------------------------------------------------- questions
class QuestionResponse {
  const QuestionResponse({
    required this.id,
    required this.authorRole,
    required this.organizationId,
    required this.text,
    required this.correctedRevisionId,
    required this.createdAt,
  });

  final String id;

  /// owner | contractor
  final String authorRole;
  final String? organizationId;
  final String text;
  final String? correctedRevisionId;
  final DateTime createdAt;

  factory QuestionResponse.fromJson(Map<String, dynamic> json) => QuestionResponse(
        id: req<String>(json, 'id'),
        authorRole: req<String>(json, 'author_role'),
        organizationId: _optString(json, 'organization_id'),
        text: req<String>(json, 'text'),
        correctedRevisionId: _optString(json, 'corrected_revision_id'),
        createdAt: reqDate(json, 'created_at'),
      );
}

class InvoiceQuestion {
  const InvoiceQuestion({
    required this.id,
    required this.invoiceId,
    required this.invoiceRevisionId,
    required this.lineId,
    required this.origin,
    required this.text,
    required this.status,
    required this.sharedAssetIds,
    required this.sharedAt,
    required this.version,
    required this.responses,
  });

  final String id;
  final String invoiceId;
  final String invoiceRevisionId;
  final String? lineId;
  final String origin;
  final String text;

  /// draft | shared | answered | closed
  final String status;
  final List<String> sharedAssetIds;
  final DateTime? sharedAt;
  final int version;
  final List<QuestionResponse> responses;

  bool get isDraft => status == 'draft';

  String get statusLabel => switch (status) {
        'draft' => 'Draft — not sent',
        'shared' => 'Sent — waiting for a reply',
        'answered' => 'Answered',
        'closed' => 'Closed',
        _ => status,
      };

  factory InvoiceQuestion.fromJson(Map<String, dynamic> json) {
    final shared = _optString(json, 'shared_at');
    return InvoiceQuestion(
      id: req<String>(json, 'id'),
      invoiceId: req<String>(json, 'invoice_id'),
      invoiceRevisionId: req<String>(json, 'invoice_revision_id'),
      lineId: _optString(json, 'line_id'),
      origin: req<String>(json, 'origin'),
      text: req<String>(json, 'text'),
      status: req<String>(json, 'status'),
      sharedAssetIds: stringList(json, 'shared_asset_ids'),
      sharedAt: shared == null ? null : DateTime.parse(shared),
      version: req<int>(json, 'version'),
      responses: [for (final r in mapList(json, 'responses')) QuestionResponse.fromJson(r)],
    );
  }
}

// ---------------------------------------------------------------------- invoice
class InvoiceSummary {
  const InvoiceSummary({
    required this.id,
    required this.title,
    required this.jobId,
    required this.standalone,
    required this.status,
    required this.version,
    required this.revisionNumber,
    required this.supplierName,
    required this.total,
    required this.currency,
    required this.createdAt,
  });

  final String id;
  final String title;
  final String? jobId;
  final bool standalone;

  /// uploaded | extraction_draft | owner_reviewed | superseded | deleted
  final String status;
  final int version;
  final int? revisionNumber;
  final String? supplierName;
  final String? total;
  final String? currency;
  final DateTime createdAt;

  String get statusLabel => invoiceStatusLabel(status);

  factory InvoiceSummary.fromJson(Map<String, dynamic> json) => InvoiceSummary(
        id: req<String>(json, 'id'),
        title: req<String>(json, 'title'),
        jobId: _optString(json, 'job_id'),
        standalone: req<bool>(json, 'standalone'),
        status: req<String>(json, 'status'),
        version: req<int>(json, 'version'),
        revisionNumber: opt<int>(json, 'revision_number'),
        supplierName: _optString(json, 'supplier_name'),
        total: _optString(json, 'total'),
        currency: _optString(json, 'currency'),
        createdAt: reqDate(json, 'created_at'),
      );
}

String invoiceStatusLabel(String status) => switch (status) {
      'uploaded' => 'Uploaded — not read yet',
      'extraction_draft' => 'Draft — check the details',
      'owner_reviewed' => 'Reviewed by you',
      'superseded' => 'Replaced by a newer revision',
      'deleted' => 'Deleted',
      _ => status,
    };

class InvoiceDetail {
  const InvoiceDetail({
    required this.summary,
    required this.provisional,
    required this.needsConfirmation,
    required this.revision,
    required this.revisions,
    required this.lines,
    required this.explanation,
    required this.questions,
    required this.extraction,
  });

  final InvoiceSummary summary;

  /// Comparisons stay provisional until you mark the current revision reviewed.
  final bool provisional;

  /// Items (`field:<name>` / `line:<id>`) that were hard to read.
  final List<String> needsConfirmation;
  final InvoiceRevision revision;
  final List<InvoiceRevisionBrief> revisions;
  final List<InvoiceLine> lines;
  final InvoiceExplanation? explanation;
  final List<InvoiceQuestion> questions;
  final ExtractionStatus extraction;

  String get id => summary.id;
  bool get standalone => summary.standalone;

  /// The newest extraction run, but only when it belongs to the current revision.
  ExtractionRun? get currentRun {
    final run = extraction.latestRun;
    return run != null && run.invoiceRevisionId == revision.id ? run : null;
  }

  /// The current revision has a document that has not been read yet.
  bool get canExtract =>
      revision.brief.sourceAssetId != null && revision.extractionStatus == 'none' && !(currentRun?.inProgress ?? false);

  factory InvoiceDetail.fromJson(Map<String, dynamic> json) {
    final exp = optMap(json, 'explanation');
    return InvoiceDetail(
      summary: InvoiceSummary.fromJson(json),
      provisional: req<bool>(json, 'provisional'),
      needsConfirmation: stringList(json, 'needs_confirmation'),
      revision: InvoiceRevision.fromJson(reqMap(json, 'revision')),
      revisions: [for (final r in mapList(json, 'revisions')) InvoiceRevisionBrief.fromJson(r)],
      lines: [for (final l in mapList(json, 'lines')) InvoiceLine.fromJson(l)],
      explanation: exp == null ? null : InvoiceExplanation.fromJson(exp),
      questions: [for (final q in mapList(json, 'questions')) InvoiceQuestion.fromJson(q)],
      extraction: ExtractionStatus.fromJson(reqMap(json, 'extraction')),
    );
  }
}

// ------------------------------------------------------------ contractor side
class SharedLine {
  const SharedLine({
    required this.lineNumber,
    required this.kind,
    required this.description,
    required this.partNumber,
    required this.quantity,
    required this.unit,
    required this.unitPrice,
    required this.lineTotal,
    required this.currency,
    required this.page,
  });

  final int lineNumber;
  final String kind;
  final String? description;
  final String? partNumber;
  final String? quantity;
  final String? unit;
  final String? unitPrice;
  final String? lineTotal;
  final String? currency;
  final int? page;

  factory SharedLine.fromJson(Map<String, dynamic> json) => SharedLine(
        lineNumber: req<int>(json, 'line_number'),
        kind: req<String>(json, 'kind'),
        description: _optString(json, 'description'),
        partNumber: _optString(json, 'part_number'),
        quantity: _optString(json, 'quantity'),
        unit: _optString(json, 'unit'),
        unitPrice: _optString(json, 'unit_price'),
        lineTotal: _optString(json, 'line_total'),
        currency: _optString(json, 'currency'),
        page: opt<int>(json, 'page'),
      );
}

class SharedAsset {
  const SharedAsset({
    required this.id,
    required this.purpose,
    required this.detectedType,
    required this.pages,
    required this.sizeBytes,
  });

  final String id;
  final String purpose;
  final String? detectedType;
  final int? pages;
  final int? sizeBytes;

  bool get isPdf => detectedType == 'application/pdf';

  String get label {
    final what = purpose == 'invoice' ? 'Invoice document' : 'Job document';
    final kind = isPdf ? 'PDF' : (detectedType?.startsWith('image/') ?? false) ? 'image' : 'file';
    final pageText = pages == null ? '' : ', $pages ${pages == 1 ? 'page' : 'pages'}';
    return '$what ($kind$pageText)';
  }

  factory SharedAsset.fromJson(Map<String, dynamic> json) => SharedAsset(
        id: req<String>(json, 'id'),
        purpose: req<String>(json, 'purpose'),
        detectedType: _optString(json, 'detected_type'),
        pages: opt<int>(json, 'pages'),
        sizeBytes: opt<int>(json, 'size_bytes'),
      );
}

class SharedInvoiceQuestion {
  const SharedInvoiceQuestion({
    required this.id,
    required this.jobId,
    required this.invoiceId,
    required this.invoiceTitle,
    required this.invoiceRevisionNumber,
    required this.text,
    required this.status,
    required this.sharedAt,
    required this.version,
    required this.line,
    required this.sharedAssets,
    required this.responses,
  });

  final String id;
  final String jobId;
  final String invoiceId;
  final String invoiceTitle;
  final int? invoiceRevisionNumber;
  final String text;

  /// shared | answered
  final String status;
  final DateTime? sharedAt;
  final int version;
  final SharedLine? line;
  final List<SharedAsset> sharedAssets;
  final List<QuestionResponse> responses;

  factory SharedInvoiceQuestion.fromJson(Map<String, dynamic> json) {
    final line = optMap(json, 'line');
    final shared = _optString(json, 'shared_at');
    return SharedInvoiceQuestion(
      id: req<String>(json, 'id'),
      jobId: req<String>(json, 'job_id'),
      invoiceId: req<String>(json, 'invoice_id'),
      invoiceTitle: req<String>(json, 'invoice_title'),
      invoiceRevisionNumber: opt<int>(json, 'invoice_revision_number'),
      text: req<String>(json, 'text'),
      status: req<String>(json, 'status'),
      sharedAt: shared == null ? null : DateTime.parse(shared),
      version: req<int>(json, 'version'),
      line: line == null ? null : SharedLine.fromJson(line),
      sharedAssets: [for (final a in mapList(json, 'shared_assets')) SharedAsset.fromJson(a)],
      responses: [for (final r in mapList(json, 'responses')) QuestionResponse.fromJson(r)],
    );
  }
}

// ----------------------------------------------------------------- private media
/// A private upload (invoice document or job document). Storage keys/paths are
/// never part of the contract.
class ServiceAsset {
  const ServiceAsset({
    required this.id,
    required this.jobId,
    required this.purpose,
    required this.status,
    required this.detectedType,
    required this.sizeBytes,
    required this.width,
    required this.height,
    required this.pages,
    required this.rejectionReason,
    required this.version,
  });

  final String id;
  final String? jobId;
  final String purpose;

  /// upload_pending | quarantined | processing | available | rejected | deleted
  final String status;
  final String? detectedType;
  final int? sizeBytes;
  final int? width;
  final int? height;
  final int? pages;
  final String? rejectionReason;
  final int version;

  bool get isAvailable => status == 'available';
  bool get isRejected => status == 'rejected';
  bool get isFinished => isAvailable || isRejected || status == 'deleted';
  bool get isPdf => detectedType == 'application/pdf';
  bool get isImage => detectedType?.startsWith('image/') ?? false;

  String get statusLabel => switch (status) {
        'upload_pending' => 'Waiting for the file',
        'quarantined' => 'Checking the file',
        'processing' => 'Preparing the file',
        'available' => 'Ready',
        'rejected' => 'Not accepted',
        'deleted' => 'Deleted',
        _ => status,
      };

  factory ServiceAsset.fromJson(Map<String, dynamic> json) => ServiceAsset(
        id: req<String>(json, 'id'),
        jobId: _optString(json, 'job_id'),
        purpose: req<String>(json, 'purpose'),
        status: req<String>(json, 'status'),
        detectedType: _optString(json, 'detected_type'),
        sizeBytes: opt<int>(json, 'size_bytes'),
        width: opt<int>(json, 'width'),
        height: opt<int>(json, 'height'),
        pages: opt<int>(json, 'pages'),
        rejectionReason: _optString(json, 'rejection_reason'),
        version: req<int>(json, 'version'),
      );
}

/// Plain-English text for why a line can't be compared with the accepted scope.
String comparisonUnavailableReasonText(String reason) => switch (reason) {
      'line_arithmetic_cannot_compute' => 'The line’s amount can’t be worked out from what is on the invoice.',
      'invoice_amount_unreadable' => 'The amount on the invoice line can’t be read.',
      'invoice_amount_unknown' => 'The invoice line has no amount.',
      'approved_amount_unknown' => 'The accepted scope has no amount for this line.',
      'invoice_unit_price_unreadable' => 'The unit price on the invoice line can’t be read.',
      'invoice_quantity_unreadable' => 'The quantity on the invoice line can’t be read.',
      'invoice_currency_unknown' =>
        'The invoice doesn’t state a single currency, so its amounts can’t be compared with the accepted scope.',
      'approved_currency_unknown' =>
        'The accepted scope doesn’t state a currency for this line, so the amounts can’t be compared.',
      _ => 'A value needed for the comparison is missing or unreadable.',
    };

/// Plain-English text for an upload rejection code.
String rejectionText(String? reason) => switch (reason) {
      'unsupported_type' || 'type_not_allowed' => 'This kind of file is not accepted. Use a PDF, JPEG or PNG.',
      'too_large' => 'The file is too large.',
      'too_many_pages' => 'The PDF has too many pages.',
      'too_many_pixels' => 'The image is too large.',
      'malware_detected' => 'The file did not pass the safety check.',
      'active_pdf_content' => 'The PDF contains active content (scripts or attachments) and was not accepted.',
      'encrypted_pdf' => 'The PDF is password-protected. Upload an unprotected copy.',
      'malformed_pdf' => 'The PDF could not be opened.',
      'pdf_metadata_unremovable' =>
        'Hidden information (metadata) in this PDF could not be removed safely. Print it to a new PDF or photograph '
            'the pages instead.',
      _ => 'The file was not accepted.',
    };

class AssetIntent {
  const AssetIntent({required this.asset, required this.uploadNeeded});

  final ServiceAsset asset;

  /// False once the server already has the content (a repeated intent).
  final bool uploadNeeded;

  factory AssetIntent.fromJson(Map<String, dynamic> json) => AssetIntent(
        asset: ServiceAsset.fromJson(reqMap(json, 'asset')),
        uploadNeeded: json['upload'] != null,
      );
}

/// A short-lived (≤ 5 minute) private download link.
class DownloadLink {
  const DownloadLink({required this.url, required this.contentType});

  final String url;
  final String? contentType;

  /// `POST /service-assets/{id}/download-url`.
  factory DownloadLink.fromAssetJson(Map<String, dynamic> json) =>
      DownloadLink(url: req<String>(json, 'url'), contentType: null);

  /// `GET …/invoice-questions/{q}/assets/{a}/download-url`.
  factory DownloadLink.fromSignedJson(Map<String, dynamic> json) =>
      DownloadLink(url: req<String>(json, 'url'), contentType: _optString(json, 'content_type'));
}
