import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// Typed measurements with explicit dimension, unit, method and provenance.
class MeasurementsTab extends ConsumerWidget {
  const MeasurementsTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(measurementsProvider(job.id));
    final owner = job.viewer.isOwner;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const InfoNote(
          'A photo is not a measurement. Inside diameter (ID) and outside diameter (OD) are different things — '
          'record only what you measured or read, with how you got it. Never disconnect or open anything to measure it.',
        ),
        if (owner && !job.isClosed)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: ActionButton(
              label: 'Record a measurement',
              icon: Icons.straighten,
              filled: true,
              onPressed: () => _record(context, ref),
            ),
          ),
        AsyncSection<List<Measurement>>(
          value: list,
          onRetry: () => ref.invalidate(measurementsProvider(job.id)),
          builder: (all) {
            final current = all.where((m) => m.isCurrent).toList();
            final old = all.where((m) => !m.isCurrent).toList();
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (current.isEmpty) const Text('No measurements yet.'),
              for (final m in current) _MeasurementCard(job: job, m: m),
              if (old.isNotEmpty) ...[
                const SizedBox(height: 16),
                Semantics(header: true, child: const Text('Earlier and superseded', style: TextStyle(fontWeight: FontWeight.bold))),
                const SizedBox(height: 8),
                for (final m in old) _MeasurementCard(job: job, m: m),
              ],
            ]);
          },
        ),
      ],
    );
  }

  Future<void> _record(BuildContext context, WidgetRef ref) async {
    final input = await showDialog<MeasurementInput>(context: context, builder: (_) => const MeasurementDialog());
    if (input == null || !context.mounted) return;
    await runJobAction(context, ref, job.id, () => ref.read(serviceJobsApiProvider).recordMeasurement(job.id, input),
        success: 'Measurement recorded');
  }
}

class _MeasurementCard extends ConsumerWidget {
  const _MeasurementCard({required this.job, required this.m});

  final ServiceJob job;
  final Measurement m;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(serviceJobsApiProvider);
    final owner = job.viewer.isOwner;
    final badge = m.isCurrent ? m.provenance.badge : (m.state == 'rejected' ? 'rejected' : 'superseded');
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: m.isCurrent ? null : HelmTheme.surface,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${m.component} — ${dimensionLabel(m.dimension)}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            ProvenanceBadge(badge),
          ]),
          const SizedBox(height: 6),
          Semantics(
            label: '${dimensionLabel(m.dimension)}: ${m.displayValue}',
            child: Text(m.displayValue, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
          ),
          if (m.thread != null)
            Text('Thread: ${[m.thread!.standard, m.thread!.size, m.thread!.pitch].whereType<String>().join(' ')}'),
          FactRow('How', methodLabel(m.method)),
          FactRow('Provenance', m.provenance.label),
          if (m.precision != null) FactRow('Precision', m.precision!),
          if (m.tool != null) FactRow('Tool', m.tool!),
          if (m.reference != null) FactRow('Scale reference', m.reference!),
          if (m.notes != null) FactRow('Notes', m.notes!),
          if (m.confirmation?.confirmedAt != null)
            FactRow('Confirmed',
                '${formatDateTime(m.confirmation!.confirmedAt!)} · ${methodLabel(m.confirmation!.method)}'),
          FactRow('Recorded', formatDateTime(m.createdAt)),
          if (m.isCurrent && !job.isClosed) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (owner)
                ActionButton(
                  label: 'Correct',
                  icon: Icons.edit,
                  onPressed: () async {
                    final input =
                        await showDialog<MeasurementInput>(context: context, builder: (_) => MeasurementDialog(initial: m));
                    if (input == null || !context.mounted) return;
                    await runJobAction(context, ref, job.id, () => api.reviseMeasurement(job.id, m.id, input),
                        success: 'Correction saved — dependent confirmations are superseded');
                  },
                ),
              if (!owner && m.state != 'contractor_confirmed')
                ActionButton(
                  label: 'Confirm measurement',
                  icon: Icons.verified_outlined,
                  filled: true,
                  onPressed: () async {
                    final r = await showDialog<(String, String)>(context: context, builder: (_) => const _ConfirmDialog());
                    if (r == null || !context.mounted) return;
                    await runJobAction(context, ref, job.id, () => api.confirmMeasurement(job.id, m.id, r.$1, note: r.$2),
                        success: 'Measurement confirmed');
                  },
                ),
              if (!owner)
                ActionButton(
                  label: 'Reject',
                  tone: Tone.bad,
                  onPressed: () async {
                    final note = await promptText(context,
                        title: 'Reject this measurement?', label: 'Why (optional)', required: false, confirm: 'Reject');
                    if (note == null || !context.mounted) return;
                    await runJobAction(context, ref, job.id, () => api.rejectMeasurement(job.id, m.id, note: note),
                        success: 'Measurement rejected');
                  },
                ),
            ]),
          ],
        ]),
      ),
    );
  }
}

class _ConfirmDialog extends StatefulWidget {
  const _ConfirmDialog();

  @override
  State<_ConfirmDialog> createState() => _ConfirmDialogState();
}

class _ConfirmDialogState extends State<_ConfirmDialog> {
  String _method = 'contractor_site';
  final _note = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Confirm this measurement'),
      content: SizedBox(
        width: 420,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('You confirm this exact value. A later correction supersedes your confirmation.'),
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: _method,
            decoration: const InputDecoration(labelText: 'How did you confirm it?'),
            items: [
              for (final mth in contractorConfirmMethods) DropdownMenuItem(value: mth, child: Text(methodLabel(mth))),
            ],
            onChanged: (v) => setState(() => _method = v ?? _method),
          ),
          TextField(controller: _note, maxLength: 1000, decoration: const InputDecoration(labelText: 'Note (optional)')),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(context, (_method, _note.text)), child: const Text('Confirm')),
      ],
    );
  }
}

/// Record or correct a measurement with an explicit dimension type, unit and method.
class MeasurementDialog extends StatefulWidget {
  const MeasurementDialog({super.key, this.initial});

  final Measurement? initial;

  @override
  State<MeasurementDialog> createState() => _MeasurementDialogState();
}

class _MeasurementDialogState extends State<MeasurementDialog> {
  final _form = GlobalKey<FormState>();
  late final _component = TextEditingController(text: widget.initial?.component);
  late final _value = TextEditingController(text: widget.initial?.valueText);
  late final _precision = TextEditingController(text: widget.initial?.precision);
  late final _tool = TextEditingController(text: widget.initial?.tool);
  late final _reference = TextEditingController(text: widget.initial?.reference);
  late final _notes = TextEditingController(text: widget.initial?.notes);
  late String? _dimension = widget.initial?.dimension;
  late String? _unit = widget.initial?.unit ?? 'mm';
  late String? _method = ownerMethods.contains(widget.initial?.method) ? widget.initial?.method : null;

  bool get _estimate => _method == 'image_estimate_with_reference';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.initial == null ? 'Record a measurement' : 'Correct this measurement'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextFormField(
                controller: _component,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'What did you measure? *', hintText: 'e.g. Pump outlet hose'),
                validator: (v) => v == null || v.trim().isEmpty ? 'Say what was measured' : null,
              ),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _dimension,
                decoration: const InputDecoration(labelText: 'Which dimension? *'),
                items: [for (final d in dimensions) DropdownMenuItem(value: d, child: Text(dimensionLabel(d)))],
                validator: (v) => v == null ? 'Choose the dimension type' : null,
                onChanged: (v) => setState(() {
                  _dimension = v;
                  if (v == 'thread') _unit = null;
                }),
              ),
              TextFormField(
                controller: _value,
                maxLength: 60,
                decoration: InputDecoration(
                  labelText: 'Value as measured or written *',
                  hintText: _dimension == 'thread' ? 'e.g. M10x1.25 or 1/2" BSP' : 'e.g. 25, 1 1/4, 20-32',
                ),
                validator: (v) => v == null || v.trim().isEmpty ? 'Enter the value' : null,
              ),
              DropdownButtonFormField<String?>(
                isExpanded: true,
                initialValue: _unit,
                decoration: const InputDecoration(labelText: 'Unit'),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('No unit (e.g. thread)')),
                  for (final u in measurementUnits) DropdownMenuItem<String?>(value: u, child: Text(u)),
                ],
                onChanged: (v) => setState(() => _unit = v),
              ),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _method,
                decoration: const InputDecoration(labelText: 'How did you get it? *'),
                items: [for (final m in ownerMethods) DropdownMenuItem(value: m, child: Text(methodLabel(m)))],
                validator: (v) => v == null ? 'Choose how you got it' : null,
                onChanged: (v) => setState(() => _method = v),
              ),
              if (_estimate)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('A photo estimate needs a visible scale reference and its uncertainty. '
                      'It stays an estimate — never a confirmed size.'),
                ),
              TextFormField(
                controller: _precision,
                maxLength: 100,
                decoration: InputDecoration(labelText: _estimate ? 'Uncertainty *' : 'Precision (optional)', hintText: '±1 mm'),
                validator: (v) => _estimate && (v == null || v.trim().isEmpty) ? 'Estimates need their uncertainty' : null,
              ),
              if (_estimate)
                TextFormField(
                  controller: _reference,
                  maxLength: 200,
                  decoration: const InputDecoration(labelText: 'Scale reference in the photo *', hintText: 'e.g. 300 mm ruler'),
                  validator: (v) => v == null || v.trim().isEmpty ? 'Name the scale reference' : null,
                ),
              TextFormField(controller: _tool, maxLength: 100, decoration: const InputDecoration(labelText: 'Tool (optional)')),
              TextFormField(controller: _notes, maxLength: 2000, decoration: const InputDecoration(labelText: 'Notes (optional)')),
            ]),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (!_form.currentState!.validate()) return;
            Navigator.pop(
              context,
              MeasurementInput(
                dimension: _dimension!,
                component: _component.text,
                valueText: _value.text,
                unit: _unit,
                precision: _precision.text,
                method: _method!,
                tool: _tool.text,
                reference: _estimate ? _reference.text : null,
                notes: _notes.text,
              ),
            );
          },
          child: const Text('Save measurement'),
        ),
      ],
    );
  }
}
