import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

/// `/service-jobs/new?vessel_id=…&entry=vessel|first_mate`: describe the problem.
/// The vessel's details are reused; the owner can correct them on the job.
class NewServiceJobScreen extends ConsumerStatefulWidget {
  const NewServiceJobScreen({super.key, this.vesselId, this.entry});

  final String? vesselId;
  final String? entry;

  @override
  ConsumerState<NewServiceJobScreen> createState() => _NewServiceJobScreenState();
}

class _NewServiceJobScreenState extends ConsumerState<NewServiceJobScreen> {
  final _form = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _issue = TextEditingController();
  final _system = TextEditingController();
  final _equipment = TextEditingController();
  final _when = TextEditingController();
  final _tried = TextEditingController();
  String? _vesselId;
  String _urgency = 'unknown';
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _vesselId = widget.vesselId;
  }

  @override
  void dispose() {
    for (final c in [_title, _issue, _system, _equipment, _when, _tried]) {
      c.dispose();
    }
    super.dispose();
  }

  String get _entryPoint => switch (widget.entry) {
        'vessel' => 'vessel',
        'first_mate' => 'first_mate',
        _ => widget.vesselId != null ? 'vessel' : 'service',
      };

  Future<void> _submit() async {
    if (!_form.currentState!.validate() || _vesselId == null) return;
    setState(() => _saving = true);
    try {
      final job = await ref.read(serviceJobsApiProvider).createJob(JobDraft(
            vesselId: _vesselId!,
            entryPoint: _entryPoint,
            title: _title.text,
            issueDescription: _issue.text,
            affectedSystem: _system.text,
            affectedEquipment: _equipment.text,
            occursWhen: _when.text,
            alreadyTried: _tried.text,
            urgency: _urgency,
          ));
      ref.invalidate(serviceJobListProvider);
      if (mounted) context.go('/service-jobs/${job.id}');
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not start the job');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final vessels = ref.watch(vesselListProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Get help with a problem')),
      body: vessels.when(
        loading: () => const LoadingView(message: 'Loading your vessels'),
        error: (e, _) =>
            ErrorView(error: e, title: 'Could not load your vessels', onRetry: () => ref.invalidate(vesselListProvider)),
        data: (list) {
          if (list.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Text('Add a vessel first so the contractor knows what they are working on.'),
                  const SizedBox(height: 12),
                  ActionButton(label: 'Add a vessel', filled: true, onPressed: () => context.go('/vessels/new')),
                ]),
              ),
            );
          }
          if (_vesselId != null && !list.any((v) => v.id == _vesselId)) _vesselId = null;
          _vesselId ??= list.length == 1 ? list.first.id : null;
          final vessel = list.where((v) => v.id == _vesselId).firstOrNull;
          return Form(
            key: _form,
            child: ContentWidth(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  const InfoNote(
                    'Start with what you have noticed. You do not need trade knowledge — First Mate will ask '
                    'for useful photos and details next, and you can stop at any point. Your draft is saved on Helm.',
                  ),
                  DropdownButtonFormField<String>(
                    isExpanded: true,
                    initialValue: _vesselId,
                    decoration: const InputDecoration(labelText: 'Vessel *'),
                    items: [
                      for (final v in list) DropdownMenuItem(value: v.id, child: Text('${v.nickname} — ${v.description}', overflow: TextOverflow.ellipsis)),
                    ],
                    validator: (v) => v == null ? 'Choose the vessel' : null,
                    onChanged: (v) => setState(() => _vesselId = v),
                  ),
                  if (vessel != null) _VesselContextPreview(vessel: vessel),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _title,
                    maxLength: 200,
                    decoration: const InputDecoration(
                      labelText: 'Short title *',
                      hintText: 'e.g. Water under the sink when the pump runs',
                    ),
                    validator: (v) => v == null || v.trim().isEmpty ? 'Give the job a short title' : null,
                  ),
                  TextFormField(
                    controller: _issue,
                    maxLines: 4,
                    maxLength: 4000,
                    decoration: const InputDecoration(labelText: 'What is happening?'),
                  ),
                  TextFormField(
                    controller: _equipment,
                    maxLength: 200,
                    decoration: const InputDecoration(
                      labelText: 'Which equipment is affected?',
                      hintText: 'e.g. Freshwater pump',
                    ),
                  ),
                  TextFormField(
                    controller: _system,
                    maxLength: 200,
                    decoration: const InputDecoration(labelText: 'Which system?', hintText: 'e.g. Freshwater, bilge, engine'),
                  ),
                  TextFormField(
                    controller: _when,
                    maxLines: 2,
                    maxLength: 2000,
                    decoration: const InputDecoration(labelText: 'When does it happen?'),
                  ),
                  TextFormField(
                    controller: _tried,
                    maxLines: 2,
                    maxLength: 2000,
                    decoration: const InputDecoration(labelText: 'What have you already tried?'),
                  ),
                  const SizedBox(height: 8),
                  const Text('How soon does it need attention?'),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final u in const ['routine', 'soon', 'urgent', 'unknown'])
                        ChoiceChip(
                          label: Text(urgencyLabel(u)),
                          selected: _urgency == u,
                          onSelected: (_) => setState(() => _urgency = u),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'If anything is smoking, sparking, smells of fuel or gas, or water is coming in fast, '
                    'stop and get help now — do not wait for a service job.',
                    style: TextStyle(fontStyle: FontStyle.italic),
                  ),
                  const SizedBox(height: 16),
                  ActionButton(
                    label: _saving ? 'Starting…' : 'Start service job',
                    icon: Icons.arrow_forward,
                    filled: true,
                    onPressed: _saving ? null : _submit,
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _VesselContextPreview extends StatelessWidget {
  const _VesselContextPreview({required this.vessel});

  final Vessel vessel;

  @override
  Widget build(BuildContext context) {
    final engine = [vessel.engineMake, vessel.engineModel, vessel.engineYear?.toString()].whereType<String>().join(' ');
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: InfoNote(
        'We will use the details saved for ${vessel.nickname}: ${vessel.description}'
        '${engine.isEmpty ? '' : ', engine $engine'}. You can confirm or correct them on the job before sharing.',
        icon: Icons.directions_boat,
      ),
    );
  }
}
