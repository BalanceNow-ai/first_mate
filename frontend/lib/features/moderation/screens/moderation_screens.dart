import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';
import 'package:helm_marine/features/moderation/data/moderation_api.dart';
import 'package:helm_marine/features/moderation/data/moderation_models.dart';

final moderationCasesProvider = FutureProvider.autoDispose.family<List<CaseSummary>, String>((ref, status) {
  final api = ref.watch(moderationApiProvider);
  requireUserId(ref);
  return api.cases(status: status);
});

final moderationCaseProvider =
    AsyncNotifierProvider.autoDispose.family<ModerationCaseController, CaseDetail, String>(ModerationCaseController.new);

class ModerationCaseController extends AsyncNotifier<CaseDetail> {
  ModerationCaseController(this.caseId);

  final String caseId;

  @override
  Future<CaseDetail> build() {
    final api = ref.watch(moderationApiProvider);
    requireUserId(ref);
    return api.caseDetail(caseId);
  }

  Future<void> act({required String action, required String reason, String? disposition}) async {
    final detail = await ref.read(moderationApiProvider).act(caseId, action: action, reason: reason, disposition: disposition);
    if (ref.mounted) state = AsyncData(detail);
  }
}

bool _isModerator(WidgetRef ref) => moderatorRoles.contains(ref.watch(currentUserProvider)?.role);

/// Profile/menu entry, shown only to moderators and admins.
class ModerationEntry extends ConsumerWidget {
  const ModerationEntry({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!_isModerator(ref)) return const SizedBox.shrink();
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: ListTile(
        leading: const Icon(Icons.shield_outlined),
        title: const Text('Moderation'),
        subtitle: const Text('Reported feedback and contested visit records'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.go('/moderation'),
      ),
    );
  }
}

class _NotAModerator extends StatelessWidget {
  const _NotAModerator();

  @override
  Widget build(BuildContext context) => const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Moderation is only available to moderators.', textAlign: TextAlign.center),
        ),
      );
}

/// `/moderation` — the case queue with a status filter.
class ModerationCasesScreen extends ConsumerStatefulWidget {
  const ModerationCasesScreen({super.key});

  @override
  ConsumerState<ModerationCasesScreen> createState() => _ModerationCasesScreenState();
}

class _ModerationCasesScreenState extends ConsumerState<ModerationCasesScreen> {
  static const _filters = {
    'active': 'Active',
    'open': 'Open',
    'under_review': 'Under review',
    'resolved': 'Resolved',
    'all': 'All',
  };
  String _status = 'active';

  @override
  Widget build(BuildContext context) {
    if (!_isModerator(ref)) {
      return Scaffold(appBar: AppBar(title: const Text('Moderation')), body: const _NotAModerator());
    }
    final cases = ref.watch(moderationCasesProvider(_status));
    return Scaffold(
      appBar: AppBar(title: const Text('Moderation')),
      body: ContentWidth(
        maxWidth: 900,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final e in _filters.entries)
                    ChoiceChip(
                      label: Text(e.value),
                      selected: _status == e.key,
                      onSelected: (_) => setState(() => _status = e.key),
                    ),
                ],
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: () => ref.refresh(moderationCasesProvider(_status).future),
                child: cases.when(
                  loading: () => const LoadingView(message: 'Loading cases…'),
                  error: (e, _) => ErrorView(
                    error: e,
                    title: 'Could not load the cases',
                    onRetry: () => ref.invalidate(moderationCasesProvider(_status)),
                  ),
                  data: (items) => ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (items.isEmpty) const Card(child: ListTile(title: Text('No cases here.'))),
                      for (final c in items)
                        Card(
                          child: ListTile(
                            minVerticalPadding: 12,
                            leading: Icon(c.resolved ? Icons.task_alt : Icons.flag_outlined,
                                color: c.resolved ? HelmTheme.success : HelmTheme.warning),
                            title: Text('${c.subject}: ${caseCategoryLabel(c.category)}'),
                            subtitle: Text([
                              caseStatusLabel(c.status),
                              if (c.restrictContent) 'Restriction requested',
                              if (c.disposition != null) dispositionLabel(c.disposition!),
                              'Reported ${formatWhen(c.createdAt)}',
                            ].join(' · ')),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: () => context.go('/moderation/cases/${c.id}'),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// `/moderation/cases/:id` — the reported content, minimal job context, the
/// action form (mandatory reason) and the audit trail.
class ModerationCaseScreen extends ConsumerWidget {
  const ModerationCaseScreen({super.key, required this.caseId});

  final String caseId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!_isModerator(ref)) {
      return Scaffold(appBar: AppBar(title: const Text('Moderation case')), body: const _NotAModerator());
    }
    final detail = ref.watch(moderationCaseProvider(caseId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Moderation case'),
        leading: BackButton(onPressed: () => context.go('/moderation')),
      ),
      body: detail.when(
        skipLoadingOnRefresh: true,
        skipLoadingOnReload: true,
        loading: () => const LoadingView(message: 'Loading the case…'),
        error: (e, _) => ErrorView(
          error: e,
          title: ApiError.from(e)?.isNotFound == true ? 'Case not found' : 'Could not load the case',
          onRetry: () => ref.invalidate(moderationCaseProvider(caseId)),
        ),
        data: (c) => ContentWidth(
          maxWidth: 900,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _CaseOverview(detail: c),
              const SectionHeading('Reported content', subtitle: 'Only what this case is about'),
              _ReportedContent(detail: c),
              const SectionHeading('Job context'),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.build_outlined),
                  title: Text(c.job.title),
                  subtitle: Text([
                    'Job status: ${c.job.status.replaceAll('_', ' ')}',
                    if (c.job.organizationName != null) 'Contractor: ${c.job.organizationName}',
                    if (c.job.disputed) 'A visit record is disputed',
                  ].join(' · ')),
                ),
              ),
              if (!c.summary.resolved) ...[
                const SectionHeading('Take an action', subtitle: 'Every action needs a reason and is recorded'),
                _ActionForm(caseId: caseId, detail: c),
              ],
              const SectionHeading('Audit trail'),
              for (final a in c.actions)
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.history),
                    title: Text(auditActionLabel(a.action)),
                    subtitle: Text('${formatWhen(a.createdAt)}'
                        '${a.contentVersion == null ? '' : ' · content version ${a.contentVersion}'}\nReason: ${a.reason}'),
                    isThreeLine: true,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CaseOverview extends StatelessWidget {
  const _CaseOverview({required this.detail});

  final CaseDetail detail;

  @override
  Widget build(BuildContext context) {
    final s = detail.summary;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text('${s.subject}: ${caseCategoryLabel(s.category)}', style: Theme.of(context).textTheme.titleLarge),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 6, children: [
              InfoPill(label: caseStatusLabel(s.status), color: s.resolved ? HelmTheme.success : HelmTheme.warning),
              if (s.restrictContent) const InfoPill(label: 'Restriction requested', color: HelmTheme.coral),
              if (s.retentionHold) const InfoPill(label: 'Retention hold', color: HelmTheme.mutedText),
            ]),
            const SizedBox(height: 8),
            Text('Reported by ${detail.reporterName ?? 'a job participant'} · ${formatWhen(s.createdAt)}'),
            const SizedBox(height: 4),
            Text('Their reason: ${detail.reason}'),
            if (s.disposition != null) ...[
              const SizedBox(height: 8),
              Text('Disposition: ${dispositionLabel(s.disposition!)}', style: const TextStyle(fontWeight: FontWeight.w600)),
              if (detail.dispositionNote != null) Text('Reason recorded: ${detail.dispositionNote}'),
            ],
          ],
        ),
      ),
    );
  }
}

class _ReportedContent extends StatelessWidget {
  const _ReportedContent({required this.detail});

  final CaseDetail detail;

  @override
  Widget build(BuildContext context) {
    final fb = detail.feedback;
    final rc = detail.reportedContent;
    final visit = detail.visitEvent;
    final children = <Widget>[];
    if (fb != null) {
      children.add(ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(fb.directionLabel),
        subtitle: Text('By ${fb.authorName ?? 'the author'}'
            '${fb.organizationName == null || fb.authorRole != 'contractor' ? '' : ' (${fb.organizationName})'}'
            ' · currently ${fb.contentState.replaceAll('_', ' ')}'),
      ));
    }
    if (rc != null) {
      children.add(Text('As reported (version ${rc.version})', style: Theme.of(context).textTheme.labelMedium));
      for (final e in rc.ratings.entries) {
        children.add(Text('${ratingLabel(e.key)}: ${e.value}'));
      }
      children.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text(rc.narrative ?? 'No comment text is available (none was written, or it was removed).'),
      ));
    }
    if (fb != null && fb.responses.isNotEmpty) {
      children.add(const SizedBox(height: 8));
      children.add(Text('Responses', style: Theme.of(context).textTheme.labelMedium));
      for (final r in fb.responses) {
        children.add(Text('${r.$1.replaceAll('_', ' ')}: ${r.$2 ?? '(not shown: ${r.$3.replaceAll('_', ' ')})'}'));
      }
    }
    if (visit != null) {
      children.add(ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text('Visit recorded as ${visit.kind}'),
        subtitle: Text('By ${visit.actorName ?? visit.actorRole} · ${formatWhen(visit.occurredAt)}'
            '${visit.note == null ? '' : '\n${visit.note}'}'),
      ));
    }
    if (children.isEmpty) children.add(const Text('The reported content is no longer available.'));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
      ),
    );
  }
}

class _ActionForm extends ConsumerStatefulWidget {
  const _ActionForm({required this.caseId, required this.detail});

  final String caseId;
  final CaseDetail detail;

  @override
  ConsumerState<_ActionForm> createState() => _ActionFormState();
}

class _ActionFormState extends ConsumerState<_ActionForm> {
  final _form = GlobalKey<FormState>();
  final _reason = TextEditingController();
  String _action = 'resolve';
  String? _disposition;
  bool _busy = false;

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate() || _busy) return;
    setState(() => _busy = true);
    try {
      await ref.read(moderationCaseProvider(widget.caseId).notifier).act(
            action: _action,
            reason: _reason.text.trim(),
            disposition: _action == 'resolve' ? _disposition : null,
          );
      _reason.clear();
      ref.invalidate(moderationCasesProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${actionLabels[_action]} — recorded.')));
      }
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final aboutReview = widget.detail.summary.feedbackId != null;
    final actions = [
      'assign',
      if (aboutReview) 'restrict',
      if (aboutReview) 'unrestrict',
      'resolve',
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _form,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DropdownButtonFormField<String>(
                  isExpanded: true,
                initialValue: _action,
                decoration: const InputDecoration(labelText: 'Action'),
                items: [for (final a in actions) DropdownMenuItem(value: a, child: Text(actionLabels[a]!))],
                onChanged: _busy ? null : (v) => setState(() => _action = v ?? 'resolve'),
              ),
              if (_action == 'resolve') ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: _disposition,
                  decoration: const InputDecoration(labelText: 'Disposition'),
                  items: [
                    for (final e in dispositionLabels.entries)
                      if (aboutReview || e.key == 'no_action' || e.key == 'eligibility_corrected')
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: _busy ? null : (v) => setState(() => _disposition = v),
                  validator: (v) => v == null ? 'Choose a disposition' : null,
                ),
              ],
              const SizedBox(height: 12),
              TextFormField(
                controller: _reason,
                enabled: !_busy,
                minLines: 2,
                maxLines: 5,
                maxLength: 2000,
                decoration: const InputDecoration(
                  labelText: 'Reason (required)',
                  helperText: 'Recorded with your name in the audit trail',
                ),
                validator: (v) => (v ?? '').trim().length < 3 ? 'Give a reason (at least 3 characters)' : null,
              ),
              const SizedBox(height: 12),
              SizedBox(
                height: 48,
                child: FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: Text(_action == 'resolve' ? 'Resolve case' : 'Record action'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
