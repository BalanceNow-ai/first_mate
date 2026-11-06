import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Visit events (scheduled / attended / completed / cancelled) and contesting a record.
class VisitsTab extends ConsumerWidget {
  const VisitsTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final visits = ref.watch(visitsProvider(job.id));
    final mySide = job.viewer.isOwner ? 'owner' : 'contractor';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const InfoNote(
          'Record what actually happened. Completion does not mean an invoice is paid or work is agreed. '
          'If the other side’s record is wrong you can contest it — a moderator looks at it; nothing is decided automatically.',
        ),
        if (!const {'archived', 'cancelled', 'completed'}.contains(job.status))
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: ActionButton(
              label: 'Record a visit',
              icon: Icons.event_available,
              filled: true,
              onPressed: () async {
                final r = await showDialog<_VisitInput>(context: context, builder: (_) => _VisitDialog(status: job.status));
                if (r == null || !context.mounted) return;
                await runJobAction(
                  context,
                  ref,
                  job.id,
                  () => ref
                      .read(serviceJobsApiProvider)
                      .recordVisit(job.id, r.kind, r.when, note: r.note, idempotencyKey: newIdempotencyKey('visit')),
                  success: 'Recorded: ${visitKindLabel(r.kind).toLowerCase()}',
                );
              },
            ),
          ),
        AsyncSection<List<VisitEvent>>(
          value: visits,
          onRetry: () => ref.invalidate(visitsProvider(job.id)),
          builder: (list) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (list.isEmpty) const Text('No visits recorded yet.'),
            for (final v in list.reversed)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: Icon(
                    switch (v.kind) {
                      'completed' => Icons.task_alt,
                      'attended' => Icons.directions_walk,
                      'cancelled' => Icons.event_busy,
                      'completion_contested' => Icons.gavel,
                      _ => Icons.event,
                    },
                    color: v.contested ? HelmTheme.warning : HelmTheme.primary,
                  ),
                  title: Text(visitKindLabel(v.kind)),
                  subtitle: Text([
                    formatDateTime(v.occurredAt),
                    'by ${v.actorName ?? humanise(v.actorRole)} (${v.actorRole})',
                    if (v.note != null) '“${v.note}”',
                    if (v.contested) 'Contested — under review',
                  ].join(' · ')),
                  trailing: const {'attended', 'completed'}.contains(v.kind) && v.actorRole != mySide && !v.contested
                      ? TextButton(
                          onPressed: () async {
                            final reason = await promptText(context,
                                title: 'Contest this record?',
                                label: 'What is wrong with it?',
                                message: 'A moderator reviews it. The record stays visible and nothing is decided automatically.',
                                confirm: 'Contest');
                            if (reason == null || !context.mounted) return;
                            await runJobAction(context, ref, job.id,
                                () => ref.read(serviceJobsApiProvider).contestVisit(job.id, v.id, reason,
                                    idempotencyKey: newIdempotencyKey('contest')),
                                success: 'Contested — a moderator will review it');
                          },
                          child: const Text('Contest'),
                        )
                      : null,
                ),
              ),
          ]),
        ),
      ],
    );
  }
}

class _VisitInput {
  const _VisitInput(this.kind, this.when, this.note);

  final String kind;
  final DateTime when;
  final String note;
}

class _VisitDialog extends StatefulWidget {
  const _VisitDialog({required this.status});

  final String status;

  @override
  State<_VisitDialog> createState() => _VisitDialogState();
}

class _VisitDialogState extends State<_VisitDialog> {
  late String _kind = widget.status == 'attended' ? 'completed' : 'attended';
  DateTime _when = DateTime.now();
  final _note = TextEditingController();

  Future<void> _pickTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _when,
      firstDate: DateTime.now().subtract(const Duration(days: 60)),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_when));
    if (!mounted) return;
    setState(() => _when = DateTime(date.year, date.month, date.day, time?.hour ?? _when.hour, time?.minute ?? _when.minute));
  }

  @override
  Widget build(BuildContext context) {
    final future = _when.isAfter(DateTime.now().add(const Duration(minutes: 1)));
    return AlertDialog(
      title: const Text('Record a visit'),
      content: SizedBox(
        width: 420,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          RadioGroup<String>(
            groupValue: _kind,
            onChanged: (v) => setState(() => _kind = v ?? _kind),
            child: Column(children: [
              for (final k in const ['scheduled', 'attended', 'completed', 'cancelled'])
                RadioListTile<String>(value: k, title: Text(visitKindLabel(k)), contentPadding: EdgeInsets.zero),
            ]),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('When'),
            subtitle: Text(formatDateTime(_when)),
            trailing: TextButton(onPressed: _pickTime, child: const Text('Change')),
          ),
          if (future && _kind != 'scheduled')
            const Text('Attendance, completion and cancellation cannot be in the future.',
                style: TextStyle(color: HelmTheme.error)),
          TextField(controller: _note, maxLength: 2000, decoration: const InputDecoration(labelText: 'Note (optional)')),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: future && _kind != 'scheduled'
              ? null
              : () => Navigator.pop(context, _VisitInput(_kind, _when, _note.text)),
          child: const Text('Record'),
        ),
      ],
    );
  }
}
