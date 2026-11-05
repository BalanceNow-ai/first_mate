import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/equipment.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/vessels/data/garage_api.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/features/vessels/widgets/form_helpers.dart';

/// Installed equipment (owner-added and applied factory records) and
/// un-applied factory OEM records, each labelled with where it came from and
/// how reliable it is. Owners add/edit/remove their equipment, apply factory
/// records and request staff verification.
class EquipmentSection extends ConsumerWidget {
  const EquipmentSection({super.key, required this.vessel});

  final Vessel vessel;

  void _refresh(WidgetRef ref) {
    ref.invalidate(vesselEquipmentProvider(vessel.id));
    ref.invalidate(verificationRequestsProvider(vessel.id));
  }

  Future<void> _run(BuildContext context, WidgetRef ref, Future<void> Function() action,
      {required String success, required String failure}) async {
    try {
      await action();
      _refresh(ref);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(success)));
      }
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: failure);
    }
  }

  Future<void> _edit(BuildContext context, WidgetRef ref, {EquipmentItem? item}) async {
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => EquipmentDialog(vesselId: vessel.id, item: item),
    );
    if (saved == true) {
      _refresh(ref);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(item == null ? 'Equipment added' : 'Equipment updated')));
      }
    }
  }

  Future<void> _remove(BuildContext context, WidgetRef ref, EquipmentItem item) async {
    final ok = await confirmAction(context,
        title: 'Remove equipment',
        message: 'Remove ${item.title} from ${vessel.nickname}? It stays in your service history but is no '
            'longer used for fitment or checklists.',
        confirmLabel: 'Remove',
        destructive: true);
    if (!ok || !context.mounted) return;
    await _run(context, ref, () => ref.read(garageApiProvider).removeEquipment(vessel.id, item.id),
        success: '${item.title} removed', failure: 'Could not remove equipment');
  }

  Future<void> _apply(BuildContext context, WidgetRef ref, {List<String>? ids}) async {
    try {
      final result = await ref.read(garageApiProvider).applyOem(vessel.id, oemIds: ids);
      _refresh(ref);
      if (!context.mounted) return;
      final skipped = result.skippedAlreadyApplied.length;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('${result.created.length} factory record${result.created.length == 1 ? '' : 's'} '
            'added to installed equipment${skipped > 0 ? ' ($skipped already applied)' : ''}'),
      ));
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not apply factory equipment');
    }
  }

  Future<void> _requestVerification(BuildContext context, WidgetRef ref) async {
    final sent = await showDialog<bool>(
      context: context,
      builder: (_) => _VerificationDialog(vesselId: vessel.id),
    );
    if (sent == true) {
      _refresh(ref);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Verification requested — Helm staff will review it')));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final equipment = ref.watch(vesselEquipmentProvider(vessel.id));
    final requests = ref.watch(verificationRequestsProvider(vessel.id)).value ?? const [];
    final pending = requests.where((r) => r.isPending).firstOrNull;
    final latest = requests.firstOrNull;
    final theme = Theme.of(context);

    return equipment.when(
      loading: () => const LoadingView(message: 'Loading equipment'),
      error: (e, _) => ErrorView(
        error: e,
        title: 'Could not load equipment',
        onRetry: () => _refresh(ref),
      ),
      data: (list) {
        final installed = list.installed;
        final factory = list.factory;
        final unverified = installed.where((i) => i.verificationStatus == 'unverified').length;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Semantics(
                    header: true,
                    child: Text('Installed equipment',
                        style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ElevatedButton.icon(
                  onPressed: () => _edit(context, ref),
                  icon: const Icon(Icons.add),
                  label: const Text('Add equipment'),
                ),
                OutlinedButton.icon(
                  onPressed: pending != null || unverified == 0 ? null : () => _requestVerification(context, ref),
                  icon: const Icon(Icons.verified_user_outlined),
                  label: const Text('Request verification'),
                ),
              ],
            ),
            if (pending != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'Verification requested ${formatDay(pending.createdAt.toLocal())} — '
                  '${pending.equipmentIds.length} item${pending.equipmentIds.length == 1 ? '' : 's'} awaiting review.',
                ),
              )
            else if (latest != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Last verification request: ${latest.status}'
                    '${latest.reviewNote == null ? '' : ' — ${latest.reviewNote}'}'),
              ),
            const SizedBox(height: 8),
            if (installed.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('No installed equipment recorded yet. Add your engine, electronics and pumps so we '
                    'can check part fitment and tailor checklists.'),
              ),
            for (final item in installed)
              EquipmentTile(
                item: item,
                onEdit: () => _edit(context, ref, item: item),
                onRemove: () => _remove(context, ref, item),
              ),
            const SizedBox(height: 16),
            Semantics(
              header: true,
              child: Text('Factory equipment',
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 4),
            if (list.modelYearId == null)
              const Text('This vessel is not linked to a boat-database model year, so no factory equipment is '
                  'listed. It links automatically when make, model and year match an entry.')
            else if (factory.isEmpty)
              const Text('All factory equipment for this model year has been added to installed equipment.')
            else ...[
              const Text('Recorded for your boat\'s model year. Not confirmed on your boat until you add it.'),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: () => _apply(context, ref),
                  icon: const Icon(Icons.playlist_add),
                  label: const Text('Add all factory equipment'),
                ),
              ),
              for (final item in factory)
                EquipmentTile(item: item, onApply: () => _apply(context, ref, ids: [item.id])),
            ],
          ],
        );
      },
    );
  }
}

/// One equipment row with provenance and reliability labels.
class EquipmentTile extends StatelessWidget {
  const EquipmentTile({super.key, required this.item, this.onEdit, this.onRemove, this.onApply});

  final EquipmentItem item;
  final VoidCallback? onEdit;
  final VoidCallback? onRemove;
  final VoidCallback? onApply;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (Color color, IconData icon) = switch (item.reliability) {
      Reliability.verified => (HelmTheme.success, Icons.verified),
      Reliability.ownerDeclared => (HelmTheme.primary, Icons.person_outline),
      Reliability.highConfidence => (HelmTheme.secondary, Icons.fact_check_outlined),
      Reliability.unconfirmed => (HelmTheme.warning, Icons.help_outline),
    };
    final details = [
      if (item.serialNumber != null) 'Serial ${item.serialNumber}',
      if (item.year != null) 'Year ${item.year}',
      if (item.installedOn != null) 'Installed ${formatDay(item.installedOn!)}',
    ];
    Widget label(String text, Color c) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: c.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(text, style: TextStyle(fontSize: 12, color: HelmTheme.darken(c, 0.15))),
        );
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, semanticLabel: item.reliability.label),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.title, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  Text(item.category.name, style: theme.textTheme.bodySmall),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      label(provenanceLabel(item.provenance), HelmTheme.mutedText),
                      label(item.reliability.label, color),
                      if (item.verificationStatus != 'unverified')
                        label(verificationLabel(item.verificationStatus),
                            item.verificationStatus == 'verified' ? HelmTheme.success : HelmTheme.warning),
                      if (item.isStandard == true) label('Standard fit', HelmTheme.mutedText),
                      if (item.isSynthetic) label('Synthetic test data', HelmTheme.coral),
                    ],
                  ),
                  if (item.displayNote != null) ...[
                    const SizedBox(height: 6),
                    Text(item.displayNote!, style: theme.textTheme.bodySmall),
                  ],
                  if (details.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(details.join(' · '), style: theme.textTheme.bodySmall),
                  ],
                  if (item.notes != null) ...[
                    const SizedBox(height: 4),
                    Text(item.notes!),
                  ],
                ],
              ),
            ),
            if (onApply != null)
              TextButton(
                onPressed: onApply,
                child: Text('Add to installed', semanticsLabel: 'Add ${item.title} to installed equipment'),
              ),
            if (onEdit != null || onRemove != null)
              PopupMenuButton<String>(
                tooltip: 'Actions for ${item.title}',
                onSelected: (v) => v == 'edit' ? onEdit?.call() : onRemove?.call(),
                itemBuilder: (_) => [
                  if (onEdit != null) const PopupMenuItem(value: 'edit', child: Text('Edit')),
                  if (onRemove != null) const PopupMenuItem(value: 'remove', child: Text('Remove')),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// Add or edit owner equipment.
class EquipmentDialog extends ConsumerStatefulWidget {
  const EquipmentDialog({super.key, required this.vesselId, this.item});

  final String vesselId;
  final EquipmentItem? item;

  @override
  ConsumerState<EquipmentDialog> createState() => _EquipmentDialogState();
}

class _EquipmentDialogState extends ConsumerState<EquipmentDialog> {
  final _formKey = GlobalKey<FormState>();
  late final _make = TextEditingController(text: widget.item?.make ?? '');
  late final _model = TextEditingController(text: widget.item?.model ?? '');
  late final _serial = TextEditingController(text: widget.item?.serialNumber ?? '');
  late final _year = TextEditingController(text: widget.item?.year?.toString() ?? '');
  late final _installed =
      TextEditingController(text: widget.item?.installedOn == null ? '' : dayString(widget.item!.installedOn!));
  late final _notes = TextEditingController(text: widget.item?.notes ?? '');
  late String? _category = widget.item?.category.slug;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_make, _model, _serial, _year, _installed, _notes]) {
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
    final draft = EquipmentDraft(
      category: _category!,
      make: _make.text.trim(),
      model: textOrNull(_model),
      serialNumber: textOrNull(_serial),
      year: intOrNull(_year),
      installedOn: parseDay(_installed.text),
      notes: textOrNull(_notes),
    );
    final api = ref.read(garageApiProvider);
    try {
      final item = widget.item;
      if (item == null) {
        await api.addEquipment(widget.vesselId, draft);
      } else {
        await api.updateEquipment(widget.vesselId, item.id, draft);
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
    final categories = ref.watch(equipmentCategoriesProvider);
    final editingFactory = widget.item != null && widget.item!.origin == 'oem';
    return FormDialog(
      title: widget.item == null ? 'Add equipment' : 'Edit equipment',
      formKey: _formKey,
      busy: _busy,
      error: _error,
      submitLabel: widget.item == null ? 'Add' : 'Save',
      onSubmit: _save,
      children: [
        if (editingFactory)
          const Text('Editing a factory record makes it your own declaration (not verified).'),
        categories.when(
          loading: () => const LinearProgressIndicator(semanticsLabel: 'Loading categories'),
          error: (e, _) => Text('Could not load categories: ${describeError(e)}'),
          data: (cats) => DropdownButtonFormField<String>(
            initialValue: cats.any((c) => c.slug == _category) ? _category : null,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Category *'),
            items: [
              for (final EquipmentCategory c in cats) DropdownMenuItem(value: c.slug, child: Text(c.name)),
            ],
            onChanged: (v) => setState(() => _category = v),
            validator: (v) => v == null ? 'Choose a category' : null,
          ),
        ),
        TextFormField(
          controller: _make,
          decoration: const InputDecoration(labelText: 'Make *', hintText: 'e.g. Garmin'),
          textCapitalization: TextCapitalization.words,
          validator: (v) {
            final t = v?.trim() ?? '';
            if (t.isEmpty) return 'Make is required';
            return t.length > 100 ? 'At most 100 characters' : null;
          },
        ),
        TextFormField(
          controller: _model,
          decoration: const InputDecoration(labelText: 'Model'),
          validator: (v) => (v?.trim().length ?? 0) > 100 ? 'At most 100 characters' : null,
        ),
        TextFormField(
          controller: _serial,
          decoration: const InputDecoration(labelText: 'Serial number'),
          validator: (v) => (v?.trim().length ?? 0) > 100 ? 'At most 100 characters' : null,
        ),
        TextFormField(
          controller: _year,
          decoration: const InputDecoration(labelText: 'Year'),
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          validator: optionalInt('Year', 1900, 2100),
        ),
        DateField(controller: _installed, label: 'Installed on'),
        TextFormField(
          controller: _notes,
          decoration: const InputDecoration(labelText: 'Notes'),
          maxLines: 3,
          validator: (v) => (v?.trim().length ?? 0) > 2000 ? 'At most 2000 characters' : null,
        ),
      ],
    );
  }
}

class _VerificationDialog extends ConsumerStatefulWidget {
  const _VerificationDialog({required this.vesselId});

  final String vesselId;

  @override
  ConsumerState<_VerificationDialog> createState() => _VerificationDialogState();
}

class _VerificationDialogState extends ConsumerState<_VerificationDialog> {
  final _formKey = GlobalKey<FormState>();
  final _note = TextEditingController();
  final _evidence = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _note.dispose();
    _evidence.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(garageApiProvider)
          .requestVerification(widget.vesselId, note: _note.text, evidenceUrl: _evidence.text);
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
      title: 'Request verification',
      formKey: _formKey,
      busy: _busy,
      error: _error,
      submitLabel: 'Send request',
      onSubmit: _send,
      children: [
        const Text('Helm staff will review your unverified installed equipment. Verified equipment is used '
            'with more confidence for fitment.'),
        TextFormField(
          controller: _note,
          decoration: const InputDecoration(labelText: 'Note for the reviewer'),
          maxLines: 3,
          validator: (v) => (v?.trim().length ?? 0) > 2000 ? 'At most 2000 characters' : null,
        ),
        TextFormField(
          controller: _evidence,
          decoration: const InputDecoration(
            labelText: 'Evidence link',
            hintText: 'e.g. a photo of the engine plate',
          ),
          keyboardType: TextInputType.url,
          validator: (v) => (v?.trim().length ?? 0) > 500 ? 'At most 500 characters' : null,
        ),
      ],
    );
  }
}
