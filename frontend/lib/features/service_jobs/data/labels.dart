/// Plain NZ-English labels for the service-jobs vocabulary. Unknown values fall
/// back to a readable form of the wire value rather than being hidden.
library;

import 'package:intl/intl.dart';

String humanise(String value) {
  final s = value.replaceAll('_', ' ').trim();
  return s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';
}

String _from(Map<String, String> m, String? v) => v == null ? 'Unknown' : (m[v] ?? humanise(v));

const jobStatusLabels = {
  'draft': 'Draft',
  'evidence_collection': 'Collecting evidence',
  'contractor_review': 'With contractor for review',
  'preparation_ready': 'Preparation ready',
  'scheduled': 'Visit scheduled',
  'attended': 'Contractor attended',
  'completed': 'Completed',
  'archived': 'Archived',
  'cancelled': 'Cancelled',
};
String jobStatusLabel(String? s) => _from(jobStatusLabels, s);

const urgencyLabels = {
  'routine': 'Routine',
  'soon': 'Soon',
  'urgent': 'Urgent',
  'unknown': 'Not sure',
};
String urgencyLabel(String? s) => _from(urgencyLabels, s);

const sectionLabels = {
  'summary': 'Problem summary and vessel details',
  'evidence': 'Photos, documents and evidence requests',
  'measurements': 'Measurements',
  'preparation': 'Preparation list and briefs',
  'access_general': 'General access and logistics',
  'access_restricted': 'Access credentials and exact location',
  'scope': 'Scope and estimates',
  'invoices': 'Invoices',
};
String sectionLabel(String s) => _from(sectionLabels, s);

/// Sections an owner can share, in display order.
const shareableSections = [
  'summary',
  'evidence',
  'measurements',
  'preparation',
  'access_general',
  'access_restricted',
  'scope',
  'invoices',
];

const assignmentStatusLabels = {
  'invited': 'Invited — waiting for them to accept',
  'accepted': 'Accepted',
  'declined': 'Declined',
  'revoked': 'Access revoked',
};
String assignmentStatusLabel(String? s) => _from(assignmentStatusLabels, s);

const evidenceCategoryLabels = {
  'overview': 'Wide view',
  'access_route': 'Access route',
  'label': 'Label or plate',
  'close_up': 'Close-up',
  'connections': 'Connections',
  'route': 'Route and fittings',
  'markings': 'Printed markings',
  'measurement': 'Measurement',
  'document': 'Document',
  'other': 'Other',
};
String evidenceCategoryLabel(String? s) => _from(evidenceCategoryLabels, s);
const evidenceCategories = [
  'overview',
  'access_route',
  'label',
  'close_up',
  'connections',
  'route',
  'markings',
  'measurement',
  'document',
  'other',
];

const requestStatusLabels = {
  'outstanding': 'Still needed',
  'answered': 'Answered',
  'unavailable': 'Gap recorded',
  'waived': 'No longer needed',
};
String requestStatusLabel(String? s) => _from(requestStatusLabels, s);

const unavailableReasonLabels = {
  'cannot_safely_access': 'I cannot safely get this',
  'not_visible': 'It is not visible',
  'not_available': 'I do not have it',
  'other': 'Another reason',
};
String unavailableReasonLabel(String? s) => _from(unavailableReasonLabels, s);

const requesterLabels = {
  'assistant': 'Suggested by First Mate',
  'owner': 'Added by you',
  'contractor': 'Requested by the contractor',
};
String requesterLabel(String? s) => _from(requesterLabels, s);

const assetStatusLabels = {
  'upload_pending': 'Waiting for upload',
  'quarantined': 'Being checked',
  'processing': 'Processing',
  'available': 'Ready',
  'rejected': 'Rejected',
  'deleted': 'Deleted',
};
String assetStatusLabel(String? s) => _from(assetStatusLabels, s);

const rejectionReasonLabels = {
  'unsupported_type': 'This file type is not supported. Use a JPEG, PNG, WebP or HEIC photo, or a PDF.',
  'too_large': 'The file is larger than allowed.',
  'too_many_pixels': 'The image is too large to process.',
  'malformed': 'The file could not be read — it may be damaged.',
  'active_content': 'The file contains active content and was refused.',
  'malware': 'The file was refused by the safety scan.',
  'scan_failed': 'The safety scan could not finish, so the file stays unavailable.',
};
String rejectionReasonLabel(String? s) => s == null ? 'Rejected' : (rejectionReasonLabels[s] ?? humanise(s));

/// A capture-quality hint for one key (`blur`, `darkness`, `framing`, `label_legibility`).
String qualityHint(String key, Object? value) {
  final v = '$value';
  if (v == 'not_assessed' || value == null) {
    return switch (key) {
      'framing' => 'Framing: not assessed',
      'label_legibility' => 'Label legibility: not assessed',
      _ => '${humanise(key)}: not assessed',
    };
  }
  return switch ((key, v)) {
    ('blur', 'ok') => 'Sharpness looks OK',
    ('blur', _) => 'Looks blurry — a sharper retake would help',
    ('darkness', 'ok') => 'Brightness looks OK',
    ('darkness', _) => 'Looks dark — more light would help',
    ('framing', 'ok') => 'Framing looks OK',
    ('framing', _) => 'Framing could be better — ${humanise(v).toLowerCase()}',
    ('label_legibility', 'ok') => 'Label looks readable',
    ('label_legibility', _) => 'Label may not be readable — retake closer, without moving anything',
    _ => '${humanise(key)}: ${humanise(v).toLowerCase()}',
  };
}

/// Quality keys shown to people (numeric scores and the method stay out of the way).
const qualityKeys = ['blur', 'darkness', 'framing', 'label_legibility'];

bool qualityNeedsRetake(Map<String, dynamic> quality) =>
    const ['blur', 'darkness'].any((k) => quality[k] != null && quality[k] != 'ok' && quality[k] != 'not_assessed');

const dimensionLabels = {
  'hose_internal_diameter': 'Hose inside diameter (ID)',
  'hose_external_diameter': 'Hose outside diameter (OD)',
  'fitting_outside_diameter': 'Fitting outside diameter',
  'thread': 'Thread (standard, size, pitch)',
  'clamp_range': 'Clamp operating range',
  'route_length': 'Route length',
  'bend_radius': 'Bend radius',
  'clearance': 'Clearance',
  'other': 'Other dimension',
};
String dimensionLabel(String? s) => _from(dimensionLabels, s);
const dimensions = [
  'hose_internal_diameter',
  'hose_external_diameter',
  'fitting_outside_diameter',
  'thread',
  'clamp_range',
  'route_length',
  'bend_radius',
  'clearance',
  'other',
];

const methodLabels = {
  'marking_read': 'Read from a printed marking',
  'owner_tape': 'Measured with a tape',
  'owner_caliper': 'Measured with a caliper',
  'owner_other': 'Measured another way',
  'image_estimate_with_reference': 'Estimated from a photo with a scale reference',
  'contractor_site': 'Checked on site by the contractor',
  'source_document': 'From a manual or specification',
};
String methodLabel(String? s) => _from(methodLabels, s);
const ownerMethods = ['owner_tape', 'owner_caliper', 'owner_other', 'marking_read', 'image_estimate_with_reference'];
const contractorConfirmMethods = ['contractor_site', 'marking_read', 'source_document'];
const measurementUnits = ['mm', 'cm', 'm', 'in', 'ft'];

/// The plain provenance badges the spec requires.
const provenanceBadgeLabels = {
  'model_suggested': 'Suggested',
  'suggested': 'Suggested',
  'owner_declared': 'Owner declared',
  'owner_measured': 'Owner measured',
  'contractor_confirmed': 'Contractor confirmed',
  'source_verified': 'Source verified',
  'rejected': 'Rejected',
  'superseded': 'Superseded',
  'unknown': 'Unknown',
};
String provenanceLabel(String? s) => _from(provenanceBadgeLabels, s);

const itemStatusLabels = {
  'suggested': 'Suggested',
  'needs_evidence': 'Needs more evidence',
  'contractor_confirmed': 'Contractor confirmed',
  'rejected': 'Rejected',
  'replaced': 'Replaced',
  'superseded': 'Superseded',
};
String itemStatusLabel(String? s) => _from(itemStatusLabels, s);

const itemCategoryLabels = {'part': 'Part', 'consumable': 'Consumable', 'tool': 'Tool'};
String itemCategoryLabel(String? s) => _from(itemCategoryLabels, s);

const catalogueMatchLabels = {
  'none': 'No catalogue match — a generic requirement is fine',
  'candidates': 'Possible catalogue products (not confirmed)',
  'confirmed': 'Catalogue product confirmed by the contractor',
};
String catalogueMatchLabel(String? s) => _from(catalogueMatchLabels, s);

const dimensionCheckLabels = {
  'not_applicable': 'Size check not applicable',
  'unknown': 'Size not checked — dimension unknown',
  'range_includes_recorded_od': 'Range includes the recorded outside diameter',
  'range_excludes_recorded_od': 'Range does not include the recorded outside diameter',
};
String dimensionCheckLabel(String? s) => _from(dimensionCheckLabels, s);

const originLabels = {
  'model': 'Suggested by photo analysis',
  'assistant': 'Suggested by First Mate',
  'owner': 'Owner',
  'contractor': 'Contractor',
};
String originLabel(String? s) => _from(originLabels, s);

const scopeStatusLabels = {
  'draft': 'Draft',
  'proposed': 'Proposed — waiting for your decision',
  'accepted': 'Accepted',
  'rejected': 'Rejected',
  'change_requested': 'Change requested',
  'superseded': 'Superseded',
};
String scopeStatusLabel(String? s) => _from(scopeStatusLabels, s);

const decisionLabels = {
  'accepted': 'Accepted',
  'rejected': 'Rejected',
  'change_requested': 'Change requested',
};
String decisionLabel(String? s) => _from(decisionLabels, s);

const estimateKindLabels = {
  'labour': 'Labour',
  'parts': 'Parts',
  'travel': 'Travel',
  'call_out': 'Call-out',
  'consumables': 'Consumables',
  'other': 'Other',
};
String estimateKindLabel(String? s) => _from(estimateKindLabels, s);

const visitKindLabels = {
  'scheduled': 'Visit scheduled',
  'attended': 'Contractor attended',
  'completed': 'Work completed',
  'cancelled': 'Visit cancelled',
  'completion_contested': 'Record contested',
};
String visitKindLabel(String? s) => _from(visitKindLabels, s);

const ackKindLabels = {
  'reviewed': 'Reviewed',
  'incomplete': 'Marked incomplete',
  'limitations_acknowledged': 'Limitations acknowledged',
  'confirmed': 'Preparation confirmed',
};
String ackKindLabel(String? s) => _from(ackKindLabels, s);

const outdatedReasonLabels = {
  'evidence_changed': 'Evidence has changed since this revision',
  'preparation_changed': 'The preparation list has changed',
  'scope_changed': 'The scope has changed',
};
String outdatedReasonLabel(String s) => _from(outdatedReasonLabels, s);

const ineligibleReasonLabels = {
  'no_attended_visit': 'Feedback opens after a visit is recorded as attended or completed.',
  'cancelled_before_attendance': 'This job was cancelled before anyone attended, so there is nothing to rate.',
  'no_accepted_assignment': 'Feedback needs a contractor who accepted this job.',
};
String ineligibleReasonLabel(String? s) => _from(ineligibleReasonLabels, s);

/// Anchors for the 1–5 scale (there is never a default answer).
const ratingAnchors = {
  1: 'Very poor',
  2: 'Poor',
  3: 'Acceptable',
  4: 'Good',
  5: 'Excellent',
};

const reportCategoryLabels = {
  'factual_dispute': 'A factual dispute',
  'opinion': 'Unfair opinion',
  'harassment': 'Harassment',
  'personal_or_security_information': 'Personal or security information',
  'other': 'Something else',
};

const memberRoleLabels = {'admin': 'Administrator', 'member': 'Member'};

const accessGeneralFields = {
  'marina': 'Marina',
  'mooring_area': 'Mooring area',
  'rendezvous': 'Where to meet',
  'parking_loading': 'Parking and loading',
  'access_hours': 'Access hours',
  'owner_attendance': 'Will you be there?',
  'locker_panel_access': 'Locker or panel access',
  'obstructions': 'Obstructions',
  'power_availability': 'Shore power',
  'water_availability': 'Water',
  'known_hazards': 'Known hazards',
  'notes': 'Other notes',
};

const accessRestrictedFields = {
  'gate_code': 'Gate code',
  'key_handover': 'Key handover',
  'contact_name': 'Contact name',
  'contact_phone': 'Contact phone',
  'berth': 'Berth',
  'exact_location': 'Exact location',
  'security_notes': 'Security notes',
};

final _dateTime = DateFormat('d MMM yyyy, h:mm a');
final _date = DateFormat('d MMM yyyy');

/// UTC timestamps are shown in local time.
String formatDateTime(DateTime t) => _dateTime.format(t.toLocal());
String formatDate(DateTime t) => _date.format(t.toLocal());

String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
