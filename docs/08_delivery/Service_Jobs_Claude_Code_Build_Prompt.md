# Claude Code — delegated service-jobs build

Copy the prompt below into Claude Code in a checkout of BalanceNow-ai/first_mate.

```text
You are the implementation lead for BalanceNow-ai/first_mate (Helm / First Mate).
The owner has requested and authorized the complete bounded service-jobs MVP specified in:
docs/04_technical_spec/Service_Jobs_and_Contractor_Assistant_Specification.md

Deliver useful working software across all four capabilities: guided problem photos and evidence; contractor preparation with provisional parts, measurements and access; “understand my invoice”; and reciprocal job-specific feedback. Work autonomously through implementation, verification, corrections, documentation and landing. Do not stop after producing a plan, scaffolding, one capability or a scripted demo.

MANDATORY PREFLIGHT — NO WORK BEFORE COMPLETION.

1. Establish repository identity, current branch, remote main SHA, worktree status and all applicable repository instructions. Preserve other people's changes. Use an isolated branch/worktree when needed.
2. Read the full new specification, docs/08_delivery/Repair_Programme.md (including decisions and the service-jobs extension), the master specification and the existing API/operations contracts. Inspect actual backend, frontend, schema, workers, auth, object storage and provider abstractions before choosing an implementation.
3. This specification was prepared against main@1ba32445a7f84a0b356682d8f5bb28ffb3711e5f. The documentation commit containing this prompt is later. Record the actual starting commit; reconcile any subsequent changes. Historical findings against f4f3a97 are not fresh defects: the repair record records a correction increment. Preserve those fixes and decisions, particularly evidence limitations, lock ordering and current-request authorization semantics.
4. Summarize the real gaps and dependency order in the canonical Repair Programme. Do not create a competing master roadmap. Mark new scope SPECIFIED_NOT_IMPLEMENTED until supported by evidence. Do not reclassify prior verified work merely because this feature is new.

Delegated authority and working method

You may make routine product, schema, API and UX choices consistent with the specification without returning for questions. Select the smallest coherent implementation that meets the entire bounded MVP. Record material assumptions and decisions in the canonical plan. Resolve ambiguity in favor of private job data, explicit human decisions, provisional AI conclusions, accurate evidence and a working manual path.

You may create branches/worktrees, edit code and docs, add migrations and necessary dependencies, run disposable local services and tests, use synthetic fixtures, delegate bounded tasks to coding/review agents if available, correct findings, commit, push and open/update a PR. You are also authorized to merge your completed change into main after the applicable existing checks and substantive review findings are satisfied. Use normal non-force updates, recheck current head and reconcile concurrent changes. Do not bypass repository protections, manufacture review approval or overwrite unrelated work. A genuine protection/tool-permission barrier is a concrete landing blocker; continue all independent work and leave a reviewable PR with the exact blocker.

Do not add new CI infrastructure or broad governance ceremony for this increment. Run meaningful local checks and any checks already required by the repository. Prefer substantial coherent increments; intermediate commits are allowed. Continue until all specified capabilities are implemented and locally verified, or a specific unavailable dependency truly prevents further progress.

Automatic authority covers local development and repository publication/landing. It does not cover production deployment or production-data migration, provisioning paid services, paid live-model calls, real customer/contractor messages, public review publication, DNS, purchases, refunds, invoice payment, or permission/credential expansion. Implement adapters, configuration and manual/local substitutes without performing those effects. Do not ask for credentials to complete work that can be proven locally. Never represent synthetic/provider-substitute evidence as live accuracy or production readiness.

Implementation requirements

A. Shared job, identity and evidence foundation
- Use the existing FastAPI/PostgreSQL/Alembic/Flutter/Celery architecture. Reuse suitable entities and services rather than introducing a separate app or generic workflow engine.
- Contractor organization membership is distinct from existing delivery/operator roles. Build verified membership, accepted assignment and explicit owner-controlled job/section grants. Directory listing or knowing an ID grants no access.
- Support owner job creation from vessel/assistant/service entry points, draft/resume, revisions, appropriate lifecycle transitions, assigned contractor inbox and private access/preparation information.
- Implement private upload/download and quarantine/scan/decode/size limits, EXIF/GPS-safe shared images, inert PDFs, short-lived URLs and scoped exports. Use a real local private object-store integration for acceptance. Never let missing scanning silently pass a production upload.
- Bind background results to exact job/evidence revisions and current authorization. Revocation and changed evidence must stop stale results from being newly published. Do not hold database locks while calling providers.

B. Guided capture, preparation and scope
- Ask useful context-specific photo requests with a reason: overview, access/clearance, markings, labels, close-ups, both ends and route where relevant. Do not impose a universal photo count. Permit “cannot safely obtain,” manual entry, unclear evidence and incomplete submission with visible gaps.
- Distinguish observed, owner-declared, owner-measured, contractor-confirmed, source-verified and unknown claims. Keep source references and actor/revision/method provenance. Changed supporting material supersedes dependent confirmations and briefs.
- Never infer an exact hose size or fitting from an unscaled photo. Separate hose ID/OD, fitting dimensions, thread, clamp range, length and application/material/pressure/temperature requirements. Preserve original units and uncertainty.
- Build provisional parts/tools/consumables with quantities and missing information. Reuse catalogue and verified-fit/mismatch/unknown controls. No fabricated SKU, suitability assertion or automatic cart purchase. Confirmation of a required dimension is not confirmation of catalogue fit or stock.
- Build owner-previewed immutable contractor briefs with symptoms, equipment, annotated evidence, access details, provisional/confirmed requirements and open questions. Contractors can acknowledge limitations and request a specific additional view.
- Build versioned scope/estimate/change decisions. Owner accepts an exact revision explicitly; neither OCR text nor AI can create an approval.

C. Understand my invoice
- Allow job-linked or standalone private invoice upload. Parse document revisions into editable draft fields and lines with page/region references and uncertainty; retain nulls for unknowns.
- Explain parts, quantities, labour/hours/rates, call-out, discounts, printed tax and totals in plain language. Use deterministic decimal/minor-unit arithmetic and source-aware rounding/currency handling, not model arithmetic.
- Compare against the recorded estimate, accepted scope and explicit changes. Explain unavailable records and uncertainty. A missing approval record is a question, not proof of unauthorized work; repeated lines are candidates, not proof of double charging.
- Provide source navigation, corrections/re-explanation, explicit sharing of selected documents/questions and attributed contractor responses/corrected invoice revisions. No automatic send, dispute, payment or ledger mutation. No unsupported fair-price, fraud, legal or tax conclusion.

D. Reciprocal feedback
- Build one review per eligible side of a real job, including contractor organization attribution. Eligibility requires accepted participation plus recorded attendance/completion, with cancellation/dispute rules from the specification; an uploaded invoice alone is insufficient.
- Use the specified separate owner-to-contractor and contractor-to-owner dimensions, 1–5 anchored scales, N/A and optional constructive narrative. Do not add payment-timeliness scoring without payment evidence.
- Implement server-controlled blind submission and a 14-day window: reveal after both submit or expiry, no visibility leaks through counts/aggregates/notifications/export, correct editing/freeze/response behavior and concurrency/idempotency.
- Keep feedback private and job-specific by default. No public owner score, blacklist, automatic denial, price penalty or automatic ranking. Working-access revocation must not erase legitimate review/response eligibility or reopen access to private media.
- Implement reporting, response, correction/addendum and authorized case moderation with auditable restricted access. Preserve a fair route for negative feedback and disputes.

E. Complete the product
- Deliver responsive Flutter journeys for owners, contractors and restricted moderators using actual typed APIs, accessible upload/capture, loading/error/retry states and persisted drafts. Do not stop at backend endpoints or static screens.
- Add migrations, constraints/indexes, idempotent tasks/outbox as needed, feature configuration, quotas, retention/deletion behavior, synthetic seed data and operations documentation.
- Treat all uploaded text/images/OCR as untrusted data. Model output cannot change sharing grants, approve scope, authorize purchases/payments or bypass deterministic fitment and permissions. Mask sensitive access/bank data from unnecessary provider inputs, logs and notifications.
- Preserve existing commerce, vessel, fitment, loyalty, delivery and authentication behavior. Avoid unrelated rewrites.

Verification and closure

Use SJ-01 through SJ-24 in the specification as the acceptance contract. Map every ID to implementation and executed evidence in the canonical Repair Programme; split partial rows honestly. Cover concrete failure behavior, not just implementation-shaped unit tests:
- cross-owner/org/role IDOR and revoked grants;
- stale async results, revised sources and repeated/concurrent mutations;
- unsupported visual measurements and uncertain suitability;
- invoice source corrections, decimal totals, mixed currencies and missing scope records;
- feedback eligibility, one-sided submission, clock-boundary reveal, N/A, duplicate submissions, restricted moderation and side-channel privacy;
- malformed/oversized/malicious uploads, provider outages and prompt-injected source documents.

Run applicable backend tests against disposable PostgreSQL, migrations from clean and existing schema, Flutter analyze/tests/build, and meaningful integrated owner/contractor journeys against the actual local API and private storage. Include a third unrelated owner/organization to prove isolation. Test the real state transitions and worker/publication path; provider fakes are appropriate for deterministic contracts. If a toolchain is unavailable, document exact failure and complete independent checks; do not claim the unexecuted check passed.

Use synthetic photos/documents. Test fixtures and fake OCR/vision prove orchestration and contracts, not marine visual accuracy. Implement configured production-provider paths and explicit unavailable/manual behavior; mark live-provider evaluation pending separately. Do not block the whole feature on broad real-world vision validation.

Reuse valid prior evidence for unchanged paths and run targeted regressions plus affected integration checks. Do not repeatedly rerun passing suites without a change or unresolved concern. Fix functional, privacy and security failures before landing; document optional hardening separately.

Finish with:
1. all four capabilities implemented, acceptance IDs dispositioned and local stack usable;
2. canonical plan, API contract, operations/run instructions and relevant specs updated with actual behavior;
3. substantive independent review where available, with findings corrected and honest reviewer attribution;
4. a landed commit, or a concrete reviewable PR if an actual landing barrier remains;
5. a concise report of starting/final SHAs, user-visible behavior, executed checks/results, requirement coverage and any specific live-validation or deployment prerequisites.

Do not return routine design questions to the owner. Investigate, choose within the specification, document the decision, fix problems and continue. Never conceal a blocker or claim completion without the specified evidence.
```
