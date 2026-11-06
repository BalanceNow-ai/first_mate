import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Reciprocal, blind, job-specific feedback.
class FeedbackTab extends ConsumerWidget {
  const FeedbackTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = ref.watch(feedbackProvider(job.id));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        AsyncSection<FeedbackOverview>(
          value: overview,
          onRetry: () => ref.invalidate(feedbackProvider(job.id)),
          builder: (o) => _FeedbackBody(job: job, o: o),
        ),
      ],
    );
  }
}

class _FeedbackBody extends StatelessWidget {
  const _FeedbackBody({required this.job, required this.o});

  final ServiceJob job;
  final FeedbackOverview o;

  @override
  Widget build(BuildContext context) {
    final subject = o.mySide == 'owner' ? 'the contractor' : 'the owner and how the job was prepared';
    if (!o.eligible) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InfoNote(ineligibleReasonLabel(o.ineligibleReason)),
        Text(o.revealRule),
      ]);
    }
    final w = o.window;
    final revealed = w?.revealed == true;
    final labels = {for (final d in o.dimensions) d.key: d.label};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      InfoNote(
        'Feedback is private to the two of you and about this job only — there are no public scores. '
        '${revealed ? 'Both reviews are now visible to both of you.' : 'Reviews stay hidden until both of you submit'
            '${w == null ? '' : ', or until ${formatDate(w.closesAt)}'}.'}',
        icon: Icons.lock_outline,
      ),
      if (o.canEdit && (o.mine == null || o.mine!.isDraft))
        _ReviewForm(job: job, o: o, subject: subject)
      else if (o.mine != null)
        _ReviewCard(job: job, review: o.mine!, labels: labels, title: 'Your review', mine: true, revealed: revealed)
      else
        const InfoNote('The feedback window has closed without a review from you.', tone: Tone.neutral),
      if (o.mine != null && !o.mine!.isDraft && !revealed)
        InfoNote(
          'Submitted. It stays hidden from the other side until they submit too'
          '${w == null ? '' : ' or until ${formatDate(w.closesAt)}'}.',
          tone: Tone.good,
          icon: Icons.check_circle_outline,
        ),
      if (o.theirs != null)
        _ReviewCard(job: job, review: o.theirs!, labels: labels, title: 'Their review of you', mine: false, revealed: revealed),
    ]);
  }
}

class _ReviewForm extends ConsumerStatefulWidget {
  const _ReviewForm({required this.job, required this.o, required this.subject});

  final ServiceJob job;
  final FeedbackOverview o;
  final String subject;

  @override
  ConsumerState<_ReviewForm> createState() => _ReviewFormState();
}

class _ReviewFormState extends ConsumerState<_ReviewForm> {
  late final Map<String, Object> _ratings = {...?widget.o.mine?.ratings};
  late final _narrative = TextEditingController(text: widget.o.mine?.narrative);
  bool _busy = false;

  Future<FeedbackOverview?> _save() => runJobAction(
        context,
        ref,
        widget.job.id,
        () => ref.read(serviceJobsApiProvider).saveFeedbackDraft(
              widget.job.id,
              widget.o.myDirection,
              ratings: _ratings,
              narrative: _narrative.text,
              expectedVersion: widget.o.mine?.version ?? 0,
            ),
      );

  Future<void> _submit() async {
    final missing = widget.o.dimensions.where((d) => !_ratings.containsKey(d.key)).toList();
    final ok = await confirmAction(
      context,
      title: 'Submit your review?',
      message: '${missing.isEmpty ? '' : '${missing.length} question(s) are unanswered and will stay unanswered (never scored as zero). '}'
          'After you submit it stays hidden until the other side submits or the window closes. '
          'You cannot change it after it is revealed.',
      confirm: 'Submit review',
    );
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    final saved = await _save();
    if (saved != null && mounted) {
      await runJobAction(
        context,
        ref,
        widget.job.id,
        () => ref.read(serviceJobsApiProvider).submitFeedback(widget.job.id, widget.o.myDirection,
            expectedVersion: saved.mine?.version, idempotencyKey: newIdempotencyKey('feedback')),
        success: 'Review submitted',
      );
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Your review of ${widget.subject}',
      subtitle: 'Rate each question 1–5, or choose “Not applicable”. Nothing is pre-selected.',
      children: [
        for (final d in widget.o.dimensions) ...[
          const SizedBox(height: 8),
          Text(d.label, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final n in ratingAnchors.keys)
              ChoiceChip(
                label: Text('$n · ${ratingAnchors[n]}'),
                tooltip: '${d.label}: $n, ${ratingAnchors[n]}',
                selected: _ratings[d.key] == n,
                onSelected: (_) => setState(() => _ratings[d.key] = n),
              ),
            ChoiceChip(
              label: const Text('Not applicable'),
              tooltip: '${d.label}: not applicable',
              selected: _ratings[d.key] == 'not_applicable',
              onSelected: (_) => setState(() => _ratings[d.key] = 'not_applicable'),
            ),
            if (_ratings.containsKey(d.key))
              TextButton(onPressed: () => setState(() => _ratings.remove(d.key)), child: const Text('Clear')),
          ]),
        ],
        const SizedBox(height: 12),
        TextField(
          controller: _narrative,
          maxLines: 4,
          maxLength: 4000,
          decoration: const InputDecoration(
            labelText: 'What happened? (optional)',
            hintText: 'Specific, constructive facts about this job — no personal or security details.',
          ),
        ),
        Wrap(spacing: 8, runSpacing: 8, children: [
          ActionButton(
            label: 'Save draft',
            icon: Icons.save_outlined,
            onPressed: _busy
                ? null
                : () async {
                    final r = await _save();
                    if (r != null && context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Draft saved (private)')));
                    }
                  },
          ),
          ActionButton(label: 'Submit review', icon: Icons.send, filled: true, onPressed: _busy ? null : _submit),
        ]),
      ],
    );
  }
}

class _ReviewCard extends ConsumerWidget {
  const _ReviewCard({
    required this.job,
    required this.review,
    required this.labels,
    required this.title,
    required this.mine,
    required this.revealed,
  });

  final ServiceJob job;
  final Review review;
  final Map<String, String> labels;
  final String title;
  final bool mine;
  final bool revealed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = review;
    final api = ref.read(serviceJobsApiProvider);
    final hidden = r.contentState != 'visible';
    final hasResponse = r.responses.any((x) => x.kind == 'response');
    return SectionCard(
      title: title,
      subtitle: '${r.author.name ?? humanise(r.author.role)} (${r.author.role})'
          '${r.organizationName == null ? '' : ' · ${r.organizationName}'}'
          '${r.visitDate == null ? '' : ' · visit ${formatDate(r.visitDate!)}'}',
      children: [
        StatusBadge(humanise(r.status), tone: r.isRevealed ? Tone.good : Tone.info, semanticPrefix: 'Review'),
        const SizedBox(height: 8),
        if (hidden)
          const InfoNote('This review is under review by a moderator and is hidden for now.', tone: Tone.warn)
        else ...[
          for (final e in labels.entries)
            FactRow(
              e.value,
              switch (r.ratings[e.key]) {
                final int n => '$n of 5 · ${ratingAnchors[n]}',
                'not_applicable' => 'Not applicable',
                _ => 'Not answered',
              },
            ),
          if (r.narrative != null) ...[const SizedBox(height: 6), Text('“${r.narrative}”')],
        ],
        for (final x in r.responses)
          Container(
            margin: const EdgeInsets.only(top: 8),
            padding: const EdgeInsets.all(8),
            color: HelmTheme.surface,
            child: Text('${humanise(x.kind)} from ${x.author.name ?? x.author.role}: '
                '${x.contentState == 'visible' ? x.text ?? '' : '(hidden while under review)'}'),
          ),
        if (revealed) ...[
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (!mine && !hasResponse)
              ActionButton(
                label: 'Respond',
                icon: Icons.reply,
                onPressed: () async {
                  final text = await promptText(context, title: 'Respond to this review', label: 'Your response', maxLength: 4000);
                  if (text == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.respondToFeedback(r.id, 'response', text),
                      success: 'Response added');
                },
              ),
            if (!mine)
              ActionButton(
                label: 'Request a correction',
                onPressed: () async {
                  final text = await promptText(context, title: 'Request a correction', label: 'What is factually wrong?', maxLength: 4000);
                  if (text == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.respondToFeedback(r.id, 'correction_request', text),
                      success: 'Correction requested');
                },
              ),
            if (mine)
              ActionButton(
                label: 'Add an addendum',
                onPressed: () async {
                  final text = await promptText(context, title: 'Add an addendum', label: 'Addendum', maxLength: 4000);
                  if (text == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.respondToFeedback(r.id, 'addendum', text),
                      success: 'Addendum added');
                },
              ),
            if (!mine)
              ActionButton(
                label: 'Report',
                icon: Icons.flag_outlined,
                tone: Tone.bad,
                onPressed: () async {
                  final report = await showDialog<(String, String, bool)>(context: context, builder: (_) => const _ReportDialog());
                  if (report == null || !context.mounted) return;
                  try {
                    await api.reportFeedback(r.id, report.$1, report.$2, restrictContent: report.$3);
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Reported — a moderator will review it. The review is not removed automatically.')));
                    }
                    refreshServiceJob(ref, job.id);
                  } catch (e) {
                    if (context.mounted) showErrorSnackBar(context, e);
                  }
                },
              ),
          ]),
        ],
      ],
    );
  }
}

class _ReportDialog extends StatefulWidget {
  const _ReportDialog();

  @override
  State<_ReportDialog> createState() => _ReportDialogState();
}

class _ReportDialogState extends State<_ReportDialog> {
  String _category = 'factual_dispute';
  final _reason = TextEditingController();
  bool _restrict = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Report this review'),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            RadioGroup<String>(
              groupValue: _category,
              onChanged: (v) => setState(() => _category = v ?? _category),
              child: Column(children: [
                for (final e in reportCategoryLabels.entries)
                  RadioListTile<String>(value: e.key, title: Text(e.value), contentPadding: EdgeInsets.zero),
              ]),
            ),
            TextField(controller: _reason, maxLength: 2000, maxLines: 3, decoration: const InputDecoration(labelText: 'Why?')),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _restrict,
              onChanged: (v) => setState(() => _restrict = v ?? false),
              title: const Text('It exposes personal or security information — hide it while it is reviewed'),
            ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (_reason.text.trim().length < 3) return;
            Navigator.pop(context, (_category, _reason.text.trim(), _restrict));
          },
          child: const Text('Report'),
        ),
      ],
    );
  }
}
