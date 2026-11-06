# Service Jobs: Guided Evidence, Contractor Preparation, Reciprocal Feedback and Invoice Understanding

**Version:** 1.0  
**Date:** 6 November 2026  
**Requirement prefix:** SJ  
**State:** Owner-requested specification; implementation not yet claimed.  
**Applies to:** BalanceNow-ai/first_mate (Helm / First Mate).

## 1. Purpose and governing position

Extend First Mate from vessel advice and parts shopping into a shared owner–contractor service journey:

Describe the problem → collect useful evidence → contractor reviews preparation → agree scope and changes → record the visit → understand the invoice → exchange reciprocal feedback.

Contractors need useful photos, equipment details, measurements and access information before attending. Owners need help collecting these without marine trade knowledge, understanding proposed parts and understanding what they were charged for. Both parties need fair feedback about a recorded job.

This is the canonical detailed specification for Features 4–7 added to the master specification. It supplements existing vessel, catalogue, fitment, identity, AI evidence and commercial requirements; it does not replace their controls or declare prior implementation defects resolved. The Repair Programme remains the single delivery/closure record.

The authorized build is the complete bounded MVP in §16. New capability must remain labelled specified/not implemented until verified. Historical phase briefs and wireframes do not override this specification's actor permissions, private-media defaults or evidence distinctions.

## 2. Product principles and scope decisions

1. Start with the owner's problem, not an exhaustive form or fixed photo count. The assistant asks the next useful question from known vessel context and outstanding contractor needs.
2. Photos are evidence of what is visible, not proof of diagnosis, material grade, dimension, hidden condition or suitability.
3. Preserve separate observations, model suggestions, owner declarations, owner measurements, contractor confirmations and source-backed fitment.
4. Contractor preparation is advisory until an authorized person confirms a requirement. A preparation item is not a purchase, quote, work instruction or approval.
5. The owner controls who receives private job material. Contractors receive access for an explicit assignment, not general access to a customer's vessel or account.
6. Feedback is reciprocal, private by default, job-specific, attributable and contestable. No public owner scores or automated blacklist.
7. Invoice explanation translates and reconciles evidence. It does not decide that a contractor is dishonest, provide legal/tax advice or declare a price fair without comparable evidence.
8. Extend the existing FastAPI/SQLAlchemy/PostgreSQL, Celery, Flutter, central fitment, AI support and notification mechanisms. Do not build a second identity system, product catalogue, ledger or approval engine.
9. Contractor organization membership is an orthogonal capability. Do not repurpose Helm Dash operator/dispatcher roles or globally promote contractors to admin.
10. The MVP supports guided capture on responsive web/mobile browsers; dedicated native camera experiences can follow. All four features must have working user journeys.

## 3. Actors and access

| Actor | Permitted access |
|---|---|
| Vessel owner / authorized job creator | Create and manage their job; collect evidence; assign a contractor; preview shared information; approve scope; upload own invoice; submit owner feedback; revoke future sharing |
| Contractor organization member assigned to job | Read explicitly shared job snapshot and enabled live updates; request evidence; annotate; confirm preparation requirements; propose scope/changes; record attendance and completion; submit contractor feedback |
| Contractor organization administrator | Manage members and job assignments within that organization; no access to unassigned private jobs |
| Platform moderator | Case-specific access to reported feedback/content under a recorded moderation reason; no automatic commercial authority |
| Platform administrator | Provision verified organization membership and resolve access/moderation incidents through audited operations; no right to impersonate owner approval |
| First Mate / processing worker | Propose questions, observations, evidence requests and explanations within server-issued job scope; cannot grant access, confirm measurements, accept quotes, buy parts, pay invoices or publish reviews |

A registered provider-directory entry alone grants no access. Local demos may provision organizations through a CLI/admin workflow. Production membership invitations must be authenticated and auditable.

Use explicit job grants with owner, organization, assigned members, permitted sections and state. Enforce every lookup/download/export/AI tool/job action server-side. Membership removal, reassignment and sharing revocation invalidate subsequent requests and background-job publication. Recheck access when publishing a delayed result. Do not claim downloaded copies can be recalled.

## 4. Shared job and evidence model

### 4.1 Core records

| Record | Required information |
|---|---|
| ServiceJob | owner_id, vessel_id, title, issue description, affected system/equipment, urgency declaration, location/access section, status, version, timestamps |
| ContractorOrganization / Membership | stable organization identity; verified user membership; organization permissions; membership status |
| JobAssignment / AccessGrant | job, organization, assigned members, consented sections, source revision/shared snapshot, invited/accepted/revoked state |
| EvidenceRequest | requesting actor, reason, requested view/measurement/question, system/component, priority, outstanding/answered/unavailable/waived state |
| EvidenceAsset | private storage key, hash, detected media type, size, capture/upload time, uploader, processing/quarantine state, derivatives, retention/deletion state |
| Observation | asset/page/frame/region reference, assertion, extracted text, origin, uncertainty, model/version if used, supersession link |
| Measurement | value/range, original unit and normalized unit, dimension type, method/tool/reference, source asset/region, recording actor, confirmation state |
| PreparationItem | category/part/function, quantity and unit, dimensions/specifications needed, candidate product IDs, status, supporting evidence, confirmer, revision |
| PreparationBriefRevision | immutable shared revision containing symptoms, access, evidence, open questions, provisional/confirmed items, assumptions and exclusions |
| ScopeRevision / ScopeDecision | proposed tasks/parts, estimate amounts/currency if present, exclusions, author; explicit owner accept/reject/request-change decision bound to revision |
| VisitEvent | attendance/completion/cancellation event, actor, time, relevant assignment, declared facts and any dispute |
| InvoiceRevision / InvoiceLine | document evidence, extracted fields, verified corrections, lines/totals, links to job/scope; no payment effect |
| InvoiceExplanationRevision / Question | source-bound explanation/reconciliation, uncertainties, owner questions and contractor responses |
| JobFeedback / Response / ModerationCase | reviewer, subject, direction, eligible job, applicable dimensions, narrative, visibility/reveal state, response and moderation history |

These are domain contracts, not a demand for one table per row. Use existing records when semantics match. IDs, foreign keys, organization/job ownership and uniqueness constraints must prevent cross-job association.

### 4.2 Evidence states and attribution

An assertion must carry one of: model_suggested, owner_declared, owner_measured, contractor_confirmed, source_verified, rejected, superseded or unknown. Confidence scores are optional hints; a high model score cannot promote an assertion to a human-confirmed or verified state.

A human confirmation records who confirmed exactly which value/revision, by what method and when. Later edits create a new revision and invalidate dependent confirmations/approvals. Source citations and attachment coordinates must resolve to the actual record. Never overwrite an original invoice with OCR corrections.

Distinguish photographed text from inferred identification. For example “image text appears to read 25 mm” is not “25 mm measured hose bore”.

## 5. Guided problem and photo intake (SJ-CAP)

### 5.1 Owner journey

Entry points: My Vessel → Get help with a problem; First Mate → Prepare a contractor visit; or an existing service job.

Start with the vessel, affected equipment, symptom, when/under what conditions it occurs, and what has already been tried. Reuse current vessel context with an explicit opportunity to correct it. Ask for location, immediate severity and access only when relevant. Save resumable drafts.

The assistant chooses the next useful evidence request from these categories:

- Wide view locating the component on the boat.
- Access route, locker/panel, working space and obstructions.
- Label/model/serial plate and equipment orientation.
- Close view of the symptom, connections and both ends of relevant hoses/cables.
- Route, bends, fittings and nearby components.
- Printed specification/size/material markings.
- Safe owner measurement with the method made explicit.
- Relevant quote, previous service record or manual.

Explain why a requested picture matters. Offer capture, upload, retake, annotate and “I cannot safely get this”. Users may proceed with gaps; the brief must show those gaps. Never require a fixed number of photographs just to reach completion.

### 5.2 Capture quality and safety

Provide best-effort blur, darkness, framing and label-legibility feedback, plus “not assessed” when unsupported. Request a better view rather than inventing missing text. Detect probable duplicate images without treating duplicates as extra evidence.

Do not ask users to disconnect hoses, remove guards, open energized equipment, approach moving machinery or disturb fuel/gas/pressurized/hot systems merely to satisfy a capture request. If further evidence needs hazardous access, flag technician inspection required and allow a safe stop. The product must not assert the boat is safe from an image.

Assistant examples are prompts, not diagnostic commands: “Can you photograph the label without moving the unit?”; “Show the locker opening from a step back”; “If the far connection is inaccessible, mark it inaccessible.”

### 5.3 Media processing

MVP defaults are configurable: up to 40 assets/job; 10 MiB/image; 20 MiB/invoice PDF; 50 pages/PDF; 250 MiB combined/job. Support JPEG/PNG/WebP, HEIC through a tested conversion path, and non-scripted PDF documents. Unsupported media receive a clear error. Limit decoded pixels, PDF rendering, CPU/time/memory, OCR output, queue retries and organization/user storage usage.

Issue authenticated upload intents tied to job, actor, media purpose and maximum size; validate content independently of extension/client MIME. Quarantine uploads until scanning and safe decode complete. Reject active content, archive bombs and malformed files. No arbitrary remote URL ingestion.

Remove EXIF/GPS from shared derivatives. Keep originals private only where needed for source evidence; do not send unnecessary metadata to a model. Provide orientation-correct derivatives, normalized coordinate references and a clear distinction between original and derived media.

Production requires private object storage, malware scanning and encrypted transport. Local object storage/scan/model substitutes must be explicit and unusable as silent production fallbacks. Scanner failure leaves content quarantined, not available. Do not ingest job photos/invoices into a global RAG corpus or use them for training by default.

## 6. Dimensions and candidate parts (SJ-PART)

### 6.1 Measurement contract

Store dimension semantics: hose internal diameter versus external diameter, fitting outside diameter, thread standard/pitch, clamp operating range, route length, bend radius or clearance. Preserve original units and precision; convert centrally without inventing precision.

The assistant may:
- Read visible markings with a source region and uncertainty.
- Guide safe manual measurement and record the owner's result.
- Offer an approximate image-based estimate only with a visible suitable reference, identified measurement plane and explicit uncertainty.

It must not:
- Infer exact dimensions from an uncalibrated image.
- Confuse outside diameter with nominal/internal bore.
- Infer fuel/exhaust/sanitation suitability, pressure/temperature rating, reinforcement, corrosion grade or thread compatibility from appearance alone.
- Treat an estimate as contractor-confirmed or source-verified fit.

Example: “25 mm ID” marking, owner-measured “32 mm OD”, and “316” printed on a clamp are three separate observations. Do not turn 316 into a diameter or assume a 25 mm clamp fits over the hose. Obtain the relevant installed diameter/range and application requirements.

### 6.2 Preparation and commercial boundaries

Create a provisional list of likely parts, consumables and tools: hose/application/length allowance, clamps and range/quantity, clips/fasteners, seals, fittings, adapters and access tools. Explain the purpose and source for each item. Maintain explicit unknowns: “fitting thread not confirmed”, “far-end connection not visible”.

Use existing catalogue IDs and central fitment for product candidates. A photo resemblance is never a verified fit. No matching product is a legitimate outcome; support generic requirements without inventing a SKU. Preparation lists must distinguish possible item, owner-confirmed measurement, contractor-confirmed requirement and confirmed catalogue match.

Contractors can confirm, replace, reject or request more evidence for each item. Changed dimensions invalidate dependent selections. Quantities include units, assumptions and any contractor-entered allowance; AI cannot invent a billable quantity. Product availability/pricing is refreshed when used commercially.

Adding items to the owner's cart requires an explicit owner action and normal stock/quantity checks. An assigned contractor's brief does not grant purchasing authority. No procurement, booking, invoice payment or refund occurs from photo analysis.

## 7. Contractor preparation and agreed work (SJ-PREP)

### 7.1 Access information

Collect only what is needed: marina/berth or mooring and rendezvous, parking/loading, gate/contact arrangements, access hours, key handover, owner attendance, locker/panel access, obstruction notes, power/water availability and known hazards. Offer photos of access where useful.

Gate codes, keys/security arrangements, contacts, exact location and invoice banking details are restricted sections. Mask by default in AI context and general exports. Separate exact access credentials from the main brief and reveal them only to specifically authorized assigned users. No public directory or feedback surface may disclose them.

### 7.2 Brief and collaboration

A contractor-ready brief contains:
1. Owner's symptoms and history, with attribution.
2. Vessel/equipment identity and confidence.
3. Annotated evidence and unresolved requests.
4. Access/logistics and safe limitations.
5. Provisional/confirmed parts, dimensions and tools.
6. Assumptions, exclusions and items needing site inspection.
7. Current proposed/accepted scope and change history.

“Ready for contractor review” means enough information to review, not that diagnosis or parts are correct. Contractor can mark preparation incomplete, request a particular view, acknowledge limitations or confirm a preparation revision. Owner previews recipients/sections before sharing. Sharing exports uses authenticated in-app access in the MVP; an emailed attachment or unprotected link is not the default.

Scope/estimate and changes are explicit revisions. Only the owner or an explicitly delegated job approver can accept a specific revision. Contractor acknowledgment is not owner approval. Model/OCR text saying “approved” cannot create a decision. Changed scope requires a new decision; uncertain information remains visible.

## 8. Understand my invoice (SJ-INV)

### 8.1 Owner journey

Entry: service job or “Understand an invoice” from My Vessel. Permit a standalone invoice without a participating contractor; do not invent a verified job relationship or grant feedback eligibility from an upload.

Upload PDF/images, extract a draft and let the owner correct key fields before relying on comparisons. Extract supplier/name, invoice/reference/date, currency, line description, part number, quantity/unit, unit price, labour hours/rate, travel/call-out, consumables, discounts, printed tax and totals where present. Preserve null/unknown; do not silently fill missing amounts. Retain exact page/region evidence and extraction certainty per field.

Provide:
- Plain-language explanation of lines and trade abbreviations.
- What work/parts relate to the reported problem or preparation list.
- What matches a quote/accepted scope and what differs.
- Additional work with the exact recorded approval, or “no approval record available”.
- Arithmetic checks and printed-total differences.
- Stated warranties, follow-up or maintenance obligations, linked to invoice evidence.
- Suggested factual questions, editable by the owner.

### 8.2 Truth, arithmetic and disputes

Use Decimal/integer minor units and declared currency. Compute quantity × rate, discount and line/subtotal differences using stated rounding policy. Do not assume every number is a price, every labour unit is an hour, that tax is included, or that foreign currency is NZD. Do not invent a tax rate or make a tax-compliance determination. Flag unclear/mixed currencies and handwritten/illegible values for confirmation.

A possible duplicate line is a question, not proof of duplicate charging. No quote/approval evidence means comparison unavailable, not unauthorized work. A supplier's correction creates a new invoice revision and invalidates the old explanation. An invoice total/description disagreement must not change an accepted scope, order, rewards ledger or payment status.

Price benchmarking is outside MVP. The assistant may explain a recorded estimate/invoice difference; it must not declare a contractor expensive/fair/fraudulent without relevant evidence. It does not automatically dispute, withhold or pay an invoice.

Owner may explicitly share an invoice question and selected supporting material with the assigned contractor. The contractor can explain or attach a correction; responses are attributed, never overwritten into the original. No third-party message is sent without the requesting user's explicit send action.

## 9. Reciprocal feedback (SJ-FB)

### 9.1 Eligibility and directions

One owner→contractor-organization review and one assigned contractor-organization→owner review per eligible job. Only actual participants can submit; self-review and unassigned users are denied. Organization feedback is authored by a named authorized member on behalf of the organization, not a separate vote from every employee.

Eligibility requires an accepted assignment and recorded attended visit/completion event. An invoice upload or AI-generated job is insufficient. Allow feedback on cancellation after attendance, with only applicable categories. Either participant can record completion; the other may contest the completion/eligibility evidence, which opens moderation without inventing an agreed fact. A cancelled-before-attendance job has no service rating. Revoking working access does not erase legitimate review/response eligibility: retain the minimum participation record needed for that purpose without restoring private job media or access credentials.

### 9.2 Questions and presentation

Use 1–5 anchored responses and not_applicable; no default rating and no converting missing answers to zero.

| Owner rates contractor | Contractor rates owner/job readiness |
|---|---|
| Communication and clarity | Accuracy of problem description and evidence |
| Arrival/access coordination | Accuracy of access/arrival arrangements |
| Explanation of work and changes | Equipment/site prepared as agreed |
| Care and agreed work delivery | Availability for agreed decisions |
| Invoice clarity and relationship to scope | Communication and handling of scope changes |

MVP excludes an automatic “paid on time” score because payment truth for contractor invoices is not established. Disputed payment allegations go through private attributed narrative/moderation rather than a machine-certified flag.

Optional narrative asks for specific, constructive job facts. Show author role, job/visit date, dimensions, not-applicable fields and the subject's response. No AI-written rating or auto-submission. AI may help the reviewer phrase their own facts but must not invent experience or sentiment.

### 9.3 Blind reveal, visibility and fairness

- Reviews are private and blind while drafting/submitted: reveal both when both submit, or after 14 days from the server-recorded eligibility event.
- The same 14-day submission window applies to both parties; edits before reveal are versioned and never expose the other party's text. At reveal, freeze the submitted review; corrections use a visible addendum/moderation history.
- Access after reveal: both job parties and authorized case moderators. The author sees their own submitted content before reveal. Avoid status/aggregate/email side channels exposing the other side's rating before reveal.
- Owner feedback about a contractor is not automatically public. Public contractor ratings are a future opt-in moderated surface; no public aggregates or owner reputation score in MVP.
- Future contractors do not see a person's private ratings by default. Owners may explicitly share selected factual preparation notes from an earlier job, with provenance and revocable future access.
- The subject can respond, request correction or report abuse. Distinguish factual dispute, opinion, harassment and personal/security information.
- Moderation records reason, actor, affected content version and action. Preserve a proportionate audit trail while honoring retention/deletion policy; “immutable history” is not permission to retain sensitive content forever.
- Reporting does not automatically suppress a legitimate negative review. While investigated, restrict exposed sensitive material and show a neutral review-under-review state where necessary; record the disposition.
- No automated booking denial, pricing penalty, credit decision, contractor ranking or owner blacklist from feedback.

Feedback eligibility, reveal time, uniqueness and authorization are server-owned and tested under concurrency. With no second submission, time-based reveal must run reliably and be idempotent.

## 10. Workflow, versioning and effects

Use independent state machines to avoid conflating attendance, work approval, invoice acceptance and review publication.

| Entity | Core states |
|---|---|
| Job | draft → evidence_collection → contractor_review → preparation_ready → scheduled → attended → completed → archived; cancelled/disputed events remain distinct |
| Assignment | invited → accepted; revoked/declined |
| Asset | upload_pending → quarantined → processing → available; rejected/deleted |
| Analysis | pending → running → draft_ready → confirmed/superseded; failed/cancelled |
| Scope | draft/proposed → accepted/rejected/superseded |
| Invoice | uploaded → extraction_draft → owner_reviewed; corrected/superseded/deleted |
| Feedback | draft → submitted_blind → revealed; reported/moderated/withdrawn according to policy |

Job completion does not mean invoice paid or review agreed. Scope acceptance does not make every diagnosis true. “Preparation ready” is a contractor/owner workflow state, not AI-certified readiness.

Every mutation validates actor and current resource version. Use expected-version checks/409 for competing edits and per-request idempotency keys for uploads, submissions, invitations, scope decisions and analysis runs. Persist actions and outbox records in the business transaction.

Each background run binds job revision, asset versions, access grant, prompt/model/config version and input digest. On completion, recheck authorization and versions before publication; stale output is kept only as a clearly superseded diagnostic or discarded. Do not hold database locks across model, scanner or storage calls. Adopt existing transaction lock order and use short claim/lease/fencing operations for workers.

## 11. Logical API and UI contracts

Paths are illustrative within /api/v1; implementation may follow repository naming conventions while retaining these operations and authority checks.

| Operation family | Required capabilities |
|---|---|
| /service-jobs | create/list/get/edit own job; versioned transition/attendance/completion |
| /service-jobs/{id}/assignments | explicit invite/accept/revoke and per-section access |
| /service-jobs/{id}/evidence-requests | propose/request/answer/waive safely; view outstanding evidence |
| /service-jobs/{id}/assets | upload intent/finalize/process/status/private download/delete |
| /service-jobs/{id}/analysis | bounded capture-quality, OCR and multimodal analysis; structured draft and retry |
| /service-jobs/{id}/measurements and /preparation-items | record, correct, confirm/reject, candidate lookup |
| /service-jobs/{id}/briefs | preview/version/publish shared revision; secure printable export |
| /service-jobs/{id}/scopes | propose revision; owner decision; approved-change references |
| /invoices | upload/extract/correct/explain; link authorized job/quote; explicit sharing/questions |
| /service-jobs/{id}/feedback | eligibility/draft/submit/reveal/response/report |
| /moderation/feedback-cases | case-scoped review and recorded disposition |

Reuse strict input schemas, stable machine error codes, pagination, UTC timestamps with local display, NZ-English defaults and typed Flutter models. Do not expose storage paths or secrets in API contracts.

UI adds “Service jobs”, a capture workspace with progress/gaps, contractor review inbox and brief, preparation list with provenance badges, agreed-work/change view, invoice explanation with side-by-side source highlights, and reciprocal feedback/response screens. Surface “suggested”, “owner measured”, “contractor confirmed”, “unknown” and “superseded” plainly.

Support large touch targets, camera/file chooser alternatives, accessible labels, text alternatives and keyboard navigation. Interrupted uploads and processing are resumable. A useful request can be completed even when the owner cannot safely obtain a photo.

## 12. Security, privacy and provider boundaries

Private storage only; short-lived authorized download URLs (default maximum 5 minutes), no predictable public object keys. Preview/export is authorized like the underlying job. Redact sensitive access/bank fields from normal summaries and model prompts. Shared documents render inertly; escape annotations and neutralize spreadsheet formulas.

Raw access credentials must not appear in feedback, analytics, model prompts, push notifications or ordinary logs. Outbox messages say an update is available and deep-link to authenticated content. Per-user/organization quotas bound model calls, processing, storage and feedback abuse. Administrative exports are audited.

Use existing model/provider adapters extended with structured vision/OCR interfaces. Models receive only authorized derivative assets needed for that task. OCR, images, PDFs, supplier text and contractor messages are untrusted data; instructions embedded in them cannot change permissions, recipients, numeric facts or workflow state. No model-driven arbitrary URL fetch/tool execution.

Deterministic checks own numeric arithmetic, revision binding, scope approvals, feedback eligibility, blind reveal, permission enforcement and catalogue fitment. Model-generated descriptions remain attributed suggestions unless independently supported. Do not reuse text-only lexical grounding as proof that a vision model saw the claimed dimension correctly.

Default retention is configurable: remove abandoned upload intents after 24 hours, unassigned inactive drafts after 90 days with advance notice, and archive completed jobs after 24 months with review/export/delete controls. Never delete records subject to an explicit active dispute retention hold without an auditable disposition. Owners can delete unshared drafts/assets immediately; shared-source deletion invalidates derivatives/explanations and leaves only minimal lawful audit markers as defined for deployment. Production retention/legal policy requires operator configuration, not an AI assertion of legal compliance.

Revoking access blocks new API/download requests immediately; existing signed URLs expire within their bounded lifetime. Do not promise immediate recall of downloaded material.

## 13. Performance and operational behaviour

Job/profile/list mutations should retain existing ordinary API targets. Vision/OCR/PDF work is asynchronous: acknowledge enqueue promptly, provide status/cancel/retry and avoid blocking normal requests while a provider runs. Report timings for processing separately from API latency.

Use private S3-compatible storage with a local acceptance equivalent, sandboxed file processing, Celery jobs and existing notification outbox. Validate production storage/scanner/provider configuration at startup or feature enablement. With missing provider credentials, capture/manual measurement/contractor review and deterministic invoice explanation must remain useful; AI analysis is explicitly unavailable, never a fake successful analysis.

No hosted CI expansion is required for this build. Existing required checks remain applicable.

## 14. Acceptance and failure matrix

| ID | Observable acceptance |
|---|---|
| SJ-01 | Owner starts from a vessel and resumes an interrupted job without losing evidence/measurements |
| SJ-02 | Assistant requests the next relevant view; blurred/hidden label yields retake/unknown, never invented model text |
| SJ-03 | “Cannot safely access” records a gap and lets owner continue without hazardous instructions |
| SJ-04 | 25 mm ID, 32 mm OD and 316 grade remain distinct; unscaled photos never yield confirmed dimensions |
| SJ-05 | Suggested hose/clamp list carries evidence, unknowns and contractor confirmation; no fabricated SKU |
| SJ-06 | Contractor sees only explicitly shared job/sections; unassigned contractors and other owners get no data |
| SJ-07 | Reassignment/revocation prevents new downloads and delayed result publication; signed URLs expire as documented |
| SJ-08 | Owner previews/publishes brief revision; contractor requests one missing picture and owner answers it |
| SJ-09 | Contractor confirms a requirement; changing measurement/engine/source supersedes dependent confirmation and parts |
| SJ-10 | Accepted scope and later change have separate explicit owner decisions; document text cannot approve either |
| SJ-11 | PDF/image invoice extraction links each key field/line to page/region; low-confidence fields require correction |
| SJ-12 | Corrected invoice quantities/rates recompute deterministically; mixed currency/missing tax remain explicit unknowns |
| SJ-13 | Quote versus invoice comparison distinguishes recorded approval, unexplained difference and unavailable evidence |
| SJ-14 | Plain-language explanation provides editable factual questions; no automatic payment/dispute/message occurs |
| SJ-15 | Standalone invoice works but creates neither contractor access nor feedback eligibility |
| SJ-16 | Two actual parties submit one review each; absent/NA scores are not zero and pre-attendance cancellation is ineligible |
| SJ-17 | Blind reviews reveal only after both submit or 14 days; API, notifications and aggregates leak no early rating |
| SJ-18 | Subject responds/reports; moderation preserves attribution, handles sensitive text and never creates public owner scores |
| SJ-19 | Malware, MIME spoofing, excessive pixels/pages/size and failed scanner stay rejected/quarantined |
| SJ-20 | Photo/PDF prompt injection cannot change access, confidence state, approvals, commercial effects or feedback |
| SJ-21 | Competing edits, double submit, worker crash/lease expiry and stale analysis yield one valid result/decision |
| SJ-22 | Model outage leaves manual capture/preparation/invoice corrections usable with honest unavailable status |
| SJ-23 | Owner→contractor preparation and invoice/feedback journeys work through real Flutter/API/PostgreSQL/local storage |
| SJ-24 | Existing catalogue, checkout, rewards and repaired evidence/lock/refund regressions remain valid |

Use safe synthetic documents and photos in tests. Local vision/OCR substitutes exercise schemas and failure variants, but cannot establish real visual accuracy. A small evaluated multimodal set must test blurry markings, scale absence, wrong equipment, misleading reference objects and embedded instructions before real-owner AI analysis is enabled. Live paid evaluation requires separate spend authority.

## 15. Worked end-to-end example

Owner: “There is water under the sink when the pump runs.”

1. First Mate reuses the boat record, asks when the leak occurs and requests an overview without asking the owner to open energized equipment.
2. Owner uploads access, pump label, hose marking and connection views. Far-end connection cannot be reached safely; gap recorded.
3. OCR suggests a hose marking reads 25 mm ID. Owner records a separate measured OD of 32 mm and a 0.8 m visible route; total required length remains unknown.
4. Brief proposes appropriate hose/application check, two candidate clamp ranges and access tools, all provisional. No product is certified from appearance.
5. Owner assigns a contractor and shares the brief, withholding gate credentials until needed. Contractor asks for one accessible label view, confirms the application and records the final requirement.
6. Contractor proposes a scope/estimate. Owner accepts that exact revision. A later changed fitting needs a new decision.
7. Owner uploads the invoice. Assistant explains labour, hose, clamps and call-out, highlights one variance with no recorded approval and drafts a factual question.
8. Contractor explains or attaches a correction. No dispute or payment is performed automatically.
9. After recorded attendance/completion, both parties provide job-specific feedback. Reviews stay blind until both submit or the window ends. Each can respond; no public owner reputation is created.

## 16. Delivery boundary

Implement all four features in one coherent programme, with substantial increments:
A. shared job/grants/media and guided capture;
B. measurement/preparation/brief and scope decisions;
C. invoice extraction/reconciliation/questions;
D. reciprocal feedback/moderation;
E. integrated acceptance, migrations, operations and closure.

The first acceptance environment is the existing local stack with synthetic organizations, owners, assets, invoices, private object storage and provider substitutes. Paid live-model calls, real contractor/customer messaging, production storage provisioning, deployment, DNS, live invoice payments and public reputation publishing are outside this build's automatic effect authority.

Do not defer an entire feature because one live provider is unavailable. Complete its code, manual path, local proof and configuration. Report implementation-required work separately from implemented/external-validation-pending work.

Not required in MVP: open marketplace bidding, contractor payout/payment processing, public ratings/owner rankings, automated price benchmarking, broad marine visual-diagnosis coverage, native AR measurement, universal manufacturer coverage or a new scheduling marketplace. These exclusions must not be used to omit the specified private owner–contractor journeys.
