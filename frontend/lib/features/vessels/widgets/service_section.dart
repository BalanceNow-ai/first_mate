import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/equipment.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/vessels/data/garage_api.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/features/vessels/widgets/form_helpers.dart';

/// Service reminders (create, edit, dismiss, delete, complete → next) and the
/// service history (create, edit, delete).
class ServiceSection extends ConsumerStatefulWidget {
  const ServiceSection({super.key, required this.vessel});

  final Vessel vessel;

  @override
  ConsumerState<ServiceSection> createState() => _ServiceSectionState();
}

class _ServiceSectionState extends ConsumerState<ServiceSection> {
  bool _showAll = false;

  String get _id => widget.vessel.id;

  void _refresh() {
    ref.invalidate(serviceRemindersProvider((_id, 'active')));
    ref.invalidate(serviceRemindersProvider((_id, 'all')));
    ref.invalidate(serviceRecordsProvider(_id));
  }

  void _snack(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _run(Future<void> Function() action, {required String success, required String failure}) async {
    try {
      await action();
      _refresh();
      _snack(success);
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: failure);
    }
  }

  Future<void> _editReminder({ServiceReminder? reminder}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => ReminderDialog(vesselId: _id, reminder: reminder),
    );
    if (ok == true) {
      _refresh();
      _snack(reminder == null ? 'Reminder added' : 'Reminder updated');
    }
  }

  Future<void> _complete(ServiceReminder reminder) async {
    final result = await showDialog<ReminderCompletion>(
      context: context,
      builder: (_) => CompleteReminderDialog(vessel: widget.vessel, reminder: reminder),
    );
    if (result == null) return;
    _refresh();
    ref.invalidate(vesselDetailProvider(_id));
    final next = result.next;
    _snack(next == null
        ? '${reminder.title} completed'
        : '${reminder.title} completed. Next: ${next.dueText.replaceFirst('Due ', 'due ')}');
  }

  Future<void> _editRecord({ServiceRecord? record}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => ServiceRecordDialog(vesselId: _id, record: record),
    );
    if (ok == true) {
      _refresh();
      _snack(record == null ? 'Service recorded' : 'Service record updated');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final reminders = ref.watch(serviceRemindersProvider((_id, _showAll ? 'all' : 'active')));
    final records = ref.watch(serviceRecordsProvider(_id));
    final api = ref.read(garageApiProvider);
    final heading = theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Semantics(header: true, child: Text('Service reminders', style: heading)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: () => _editReminder(),
              icon: const Icon(Icons.add_alarm),
              label: const Text('Add reminder'),
            ),
            FilterChip(
              label: const Text('Show completed & dismissed'),
              selected: _showAll,
              onSelected: (v) => setState(() => _showAll = v),
            ),
          ],
        ),
        const SizedBox(height: 8),
        reminders.when(
          loading: () => const Padding(padding: EdgeInsets.all(16), child: LoadingView(message: 'Loading reminders')),
          error: (e, _) => ErrorView(error: e, title: 'Could not load reminders', onRetry: _refresh),
          data: (list) => list.isEmpty
              ? const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: Text('No reminders. Add one for your next service, impeller change or antifouling.'),
                )
              : Column(
                  children: [
                    for (final r in list)
                      _ReminderTile(
                        reminder: r,
                        onComplete: r.isActive ? () => _complete(r) : null,
                        onEdit: r.status == 'completed' ? null : () => _editReminder(reminder: r),
                        onDismiss: r.isActive
                            ? () => _run(() => api.updateReminder(_id, r.id, {'status': 'dismissed'}),
                                success: 'Reminder dismissed', failure: 'Could not dismiss reminder')
                            : null,
                        onDelete: () async {
                          final ok = await confirmAction(context,
                              title: 'Delete reminder',
                              message: 'Delete "${r.title}"?',
                              confirmLabel: 'Delete',
                              destructive: true);
                          if (ok) {
                            await _run(() => api.deleteReminder(_id, r.id),
                                success: 'Reminder deleted', failure: 'Could not delete reminder');
                          }
                        },
                      ),
                  ],
                ),
        ),
        const SizedBox(height: 24),
        Semantics(header: true, child: Text('Service history', style: heading)),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: ElevatedButton.icon(
            onPressed: () => _editRecord(),
            icon: const Icon(Icons.build_outlined),
            label: const Text('Record a service'),
          ),
        ),
        const SizedBox(height: 8),
        records.when(
          loading: () => const Padding(padding: EdgeInsets.all(16), child: LoadingView(message: 'Loading service history')),
          error: (e, _) => ErrorView(error: e, title: 'Could not load service history', onRetry: _refresh),
          data: (list) => list.isEmpty
              ? const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: Text('No services recorded yet.'),
                )
              : Column(
                  children: [
                    for (final r in list)
                      _RecordTile(
                        record: r,
                        onEdit: () => _editRecord(record: r),
                        onDelete: () async {
                          final ok = await confirmAction(context,
                              title: 'Delete service record',
                              message: 'Delete "${r.serviceType}" on ${formatDay(r.performedOn)}?',
                              confirmLabel: 'Delete',
                              destructive: true);
                          if (ok) {
                            await _run(() => api.deleteServiceRecord(_id, r.id),
                                success: 'Service record deleted', failure: 'Could not delete service record');
                          }
                        },
                      ),
                  ],
                ),
        ),
      ],
    );
  }
}

class _ReminderTile extends StatelessWidget {
  const _ReminderTile({
    required this.reminder,
    this.onComplete,
    this.onEdit,
    this.onDismiss,
    this.onDelete,
  });

  final ServiceReminder reminder;
  final VoidCallback? onComplete;
  final VoidCallback? onEdit;
  final VoidCallback? onDismiss;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final r = reminder;
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              r.isDue ? Icons.notification_important : Icons.alarm,
              color: r.isDue ? HelmTheme.error : HelmTheme.primary,
              semanticLabel: r.isDue ? 'Due now' : null,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(r.title, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  Text(r.dueText),
                  if (r.intervalText != null) Text(r.intervalText!, style: theme.textTheme.bodySmall),
                  if (r.isDue)
                    const Text('Due now', style: TextStyle(color: HelmTheme.error, fontWeight: FontWeight.w600)),
                  if (!r.isActive) Text('Status: ${r.status}', style: theme.textTheme.bodySmall),
                ],
              ),
            ),
            if (onComplete != null)
              TextButton(
                onPressed: onComplete,
                child: Text('Complete', semanticsLabel: 'Complete ${r.title}'),
              ),
            PopupMenuButton<String>(
              tooltip: 'Actions for ${r.title}',
              onSelected: (v) => switch (v) {
                'edit' => onEdit?.call(),
                'dismiss' => onDismiss?.call(),
                _ => onDelete?.call(),
              },
              itemBuilder: (_) => [
                if (onEdit != null) const PopupMenuItem(value: 'edit', child: Text('Edit')),
                if (onDismiss != null) const PopupMenuItem(value: 'dismiss', child: Text('Dismiss')),
                if (onDelete != null) const PopupMenuItem(value: 'delete', child: Text('Delete')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _RecordTile extends StatelessWidget {
  const _RecordTile({required this.record, required this.onEdit, required this.onDelete});

  final ServiceRecord record;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final r = record;
    final theme = Theme.of(context);
    final facts = [
      formatDay(r.performedOn),
      if (r.engineHours != null) '${r.engineHours} engine hours',
      if (r.providerName != null) r.providerName!,
      if (r.costText != null) r.costText!,
    ];
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.build_circle_outlined, color: HelmTheme.primary),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(r.serviceType, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  Text(facts.join(' · ')),
                  if (r.notes != null) Text(r.notes!, style: theme.textTheme.bodySmall),
                ],
              ),
            ),
            PopupMenuButton<String>(
              tooltip: 'Actions for ${r.serviceType}',
              onSelected: (v) => v == 'edit' ? onEdit() : onDelete(),
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'edit', child: Text('Edit')),
                PopupMenuItem(value: 'delete', child: Text('Delete')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

final _digits = [FilteringTextInputFormatter.digitsOnly];

/// Create or edit a reminder (needs a due date and/or due engine hours).
class ReminderDialog extends ConsumerStatefulWidget {
  const ReminderDialog({super.key, required this.vesselId, this.reminder});

  final String vesselId;
  final ServiceReminder? reminder;

  @override
  ConsumerState<ReminderDialog> createState() => _ReminderDialogState();
}

class _ReminderDialogState extends ConsumerState<ReminderDialog> {
  final _formKey = GlobalKey<FormState>();
  late final _title = TextEditingController(text: widget.reminder?.title ?? '');
  late final _dueOn =
      TextEditingController(text: widget.reminder?.dueOn == null ? '' : dayString(widget.reminder!.dueOn!));
  late final _dueHours = TextEditingController(text: widget.reminder?.dueEngineHours?.toString() ?? '');
  late final _months = TextEditingController(text: widget.reminder?.intervalMonths?.toString() ?? '');
  late final _hours = TextEditingController(text: widget.reminder?.intervalHours?.toString() ?? '');
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_title, _dueOn, _dueHours, _months, _hours]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final draft = ReminderDraft(
      title: _title.text.trim(),
      dueOn: parseDay(_dueOn.text),
      dueEngineHours: intOrNull(_dueHours),
      intervalMonths: intOrNull(_months),
      intervalHours: intOrNull(_hours),
      equipmentId: widget.reminder?.equipmentId,
    );
    if (draft.dueOn == null && draft.dueEngineHours == null) {
      setState(() => _error = 'Set a due date and/or due engine hours');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = ref.read(garageApiProvider);
    try {
      final r = widget.reminder;
      if (r == null) {
        await api.addReminder(widget.vesselId, draft);
      } else {
        await api.updateReminder(widget.vesselId, r.id, draft.toUpdateJson());
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = describeError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FormDialog(
      title: widget.reminder == null ? 'Add reminder' : 'Edit reminder',
      formKey: _formKey,
      busy: _busy,
      error: _error,
      submitLabel: 'Save',
      onSubmit: _save,
      children: [
        TextFormField(
          controller: _title,
          decoration: const InputDecoration(labelText: 'What needs doing *', hintText: 'e.g. Replace impeller'),
          validator: (v) {
            final t = v?.trim() ?? '';
            if (t.isEmpty) return 'Title is required';
            return t.length > 200 ? 'At most 200 characters' : null;
          },
        ),
        DateField(controller: _dueOn, label: 'Due date'),
        TextFormField(
          controller: _dueHours,
          decoration: const InputDecoration(labelText: 'Due at engine hours'),
          keyboardType: TextInputType.number,
          inputFormatters: _digits,
          validator: optionalInt('Engine hours', 0, 100000),
        ),
        const Text('Repeat (optional): when completed, the next reminder is created from these intervals.'),
        TextFormField(
          controller: _months,
          decoration: const InputDecoration(labelText: 'Repeat every (months)'),
          keyboardType: TextInputType.number,
          inputFormatters: _digits,
          validator: optionalInt('Months', 1, 120),
        ),
        TextFormField(
          controller: _hours,
          decoration: const InputDecoration(labelText: 'Repeat every (engine hours)'),
          keyboardType: TextInputType.number,
          inputFormatters: _digits,
          validator: optionalInt('Hours', 1, 10000),
        ),
      ],
    );
  }
}

/// Complete a reminder; returns the server's completion (with the next one).
class CompleteReminderDialog extends ConsumerStatefulWidget {
  const CompleteReminderDialog({super.key, required this.vessel, required this.reminder});

  final Vessel vessel;
  final ServiceReminder reminder;

  @override
  ConsumerState<CompleteReminderDialog> createState() => _CompleteReminderDialogState();
}

class _CompleteReminderDialogState extends ConsumerState<CompleteReminderDialog> {
  final _formKey = GlobalKey<FormState>();
  final _date = TextEditingController(text: dayString(DateTime.now()));
  late final _hours = TextEditingController(text: widget.vessel.engineHours?.toString() ?? '');
  final _notes = TextEditingController();
  bool _record = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _date.dispose();
    _hours.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await ref.read(garageApiProvider).completeReminder(
            widget.vessel.id,
            widget.reminder.id,
            completedOn: parseDay(_date.text),
            engineHours: intOrNull(_hours),
            recordService: _record,
            notes: _notes.text,
          );
      if (mounted) Navigator.pop(context, result);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = describeError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FormDialog(
      title: 'Complete "${widget.reminder.title}"',
      formKey: _formKey,
      busy: _busy,
      error: _error,
      submitLabel: 'Complete',
      onSubmit: _save,
      children: [
        DateField(controller: _date, label: 'Completed on', required: true),
        TextFormField(
          controller: _hours,
          decoration: const InputDecoration(labelText: 'Engine hours at completion'),
          keyboardType: TextInputType.number,
          inputFormatters: _digits,
          validator: optionalInt('Engine hours', 0, 100000),
        ),
        CheckboxListTile(
          value: _record,
          onChanged: (v) => setState(() => _record = v ?? true),
          title: const Text('Add to service history'),
          contentPadding: EdgeInsets.zero,
        ),
        TextFormField(
          controller: _notes,
          decoration: const InputDecoration(labelText: 'Notes'),
          maxLines: 2,
        ),
        if (widget.reminder.intervalText != null)
          Text('${widget.reminder.intervalText}: the next reminder will be created automatically.'),
      ],
    );
  }
}

/// Create or edit a service record. Cost is entered in dollars and sent as cents.
class ServiceRecordDialog extends ConsumerStatefulWidget {
  const ServiceRecordDialog({super.key, required this.vesselId, this.record});

  final String vesselId;
  final ServiceRecord? record;

  @override
  ConsumerState<ServiceRecordDialog> createState() => _ServiceRecordDialogState();
}

class _ServiceRecordDialogState extends ConsumerState<ServiceRecordDialog> {
  final _formKey = GlobalKey<FormState>();
  late final _type = TextEditingController(text: widget.record?.serviceType ?? '');
  late final _date = TextEditingController(
      text: dayString(widget.record?.performedOn ?? DateTime.now()));
  late final _hours = TextEditingController(text: widget.record?.engineHours?.toString() ?? '');
  late final _provider = TextEditingController(text: widget.record?.providerName ?? '');
  late final _cost = TextEditingController(
      text: widget.record?.costCents == null ? '' : centsToDollarsText(widget.record!.costCents!));
  late final _notes = TextEditingController(text: widget.record?.notes ?? '');
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_type, _date, _hours, _provider, _cost, _notes]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final draft = ServiceRecordDraft(
      serviceType: _type.text.trim(),
      performedOn: parseDay(_date.text)!,
      engineHours: intOrNull(_hours),
      providerName: textOrNull(_provider),
      costCents: parseDollarsToCents(_cost.text),
      notes: textOrNull(_notes),
      equipmentId: widget.record?.equipmentId,
    );
    final api = ref.read(garageApiProvider);
    try {
      final r = widget.record;
      if (r == null) {
        await api.addServiceRecord(widget.vesselId, draft);
      } else {
        await api.updateServiceRecord(widget.vesselId, r.id, draft);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = describeError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FormDialog(
      title: widget.record == null ? 'Record a service' : 'Edit service record',
      formKey: _formKey,
      busy: _busy,
      error: _error,
      submitLabel: 'Save',
      onSubmit: _save,
      children: [
        TextFormField(
          controller: _type,
          decoration: const InputDecoration(labelText: 'Service *', hintText: 'e.g. 100-hour service'),
          validator: (v) {
            final t = v?.trim() ?? '';
            if (t.isEmpty) return 'Service is required';
            return t.length > 120 ? 'At most 120 characters' : null;
          },
        ),
        DateField(controller: _date, label: 'Performed on', required: true),
        TextFormField(
          controller: _hours,
          decoration: const InputDecoration(labelText: 'Engine hours'),
          keyboardType: TextInputType.number,
          inputFormatters: _digits,
          validator: optionalInt('Engine hours', 0, 100000),
        ),
        TextFormField(
          controller: _provider,
          decoration: const InputDecoration(labelText: 'Done by'),
          validator: (v) => (v?.trim().length ?? 0) > 200 ? 'At most 200 characters' : null,
        ),
        TextFormField(
          controller: _cost,
          decoration: const InputDecoration(labelText: 'Cost (NZD)', prefixText: r'$'),
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          validator: (v) {
            try {
              parseDollarsToCents(v ?? '');
              return null;
            } on FormatException catch (e) {
              return e.message;
            }
          },
        ),
        TextFormField(
          controller: _notes,
          decoration: const InputDecoration(labelText: 'Notes'),
          maxLines: 3,
          validator: (v) => (v?.trim().length ?? 0) > 4000 ? 'At most 4000 characters' : null,
        ),
      ],
    );
  }
}
