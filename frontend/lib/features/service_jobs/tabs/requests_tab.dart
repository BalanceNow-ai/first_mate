import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';
import 'package:helm_marine/features/service_jobs/widgets/evidence_widgets.dart';

/// Contractor: the shared evidence, its gaps, and asking for a specific additional view.
class RequestsTab extends ConsumerWidget {
  const RequestsTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final requests = ref.watch(evidenceRequestsProvider(job.id));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Evidence requests',
          subtitle: 'Ask the owner for a specific view. They are never asked to do anything unsafe — '
              'if they cannot safely get it, a gap is recorded for you to check on site.',
          trailing: job.isClosed
              ? null
              : FilledButton.icon(
                  onPressed: () => requestView(context, ref, job),
                  icon: const Icon(Icons.add_a_photo_outlined),
                  label: const Text('Request a view'),
                ),
          children: [
            AsyncSection<List<EvidenceRequest>>(
              value: requests,
              onRetry: () => ref.invalidate(evidenceRequestsProvider(job.id)),
              builder: (list) => list.isEmpty
                  ? const Text('No requests yet.')
                  : Column(children: [
                      for (final r in list)
                        RequestTile(
                          request: r,
                          actions: [
                            if (r.isOutstanding && r.requesterRole == 'contractor')
                              ActionButton(
                                label: 'No longer needed',
                                onPressed: () => runJobAction(context, ref, job.id,
                                    () => ref.read(serviceJobsApiProvider).waive(job.id, r.id, expectedVersion: r.version),
                                    success: 'Request withdrawn'),
                              ),
                          ],
                        ),
                    ]),
            ),
          ],
        ),
        AssetsSection(job: job, title: 'Shared photos and documents'),
        ObservationsSection(job: job),
      ],
    );
  }
}

/// The view/measurement a contractor asks for (`EvidenceRequestCreate`).
class RequestedView {
  const RequestedView(this.category, this.prompt, this.reason, this.component);

  final String category;
  final String prompt;
  final String reason;
  final String? component;

  Map<String, dynamic> toJson() => {
        'category': category,
        'prompt': prompt,
        'reason': reason,
        if (component != null && component!.isNotEmpty) 'component': component,
      };
}

Future<RequestedView?> askForView(BuildContext context, {String title = 'Request a specific view'}) =>
    showDialog<RequestedView>(context: context, builder: (_) => _RequestViewDialog(title: title));

Future<void> requestView(BuildContext context, WidgetRef ref, ServiceJob job) async {
  final v = await askForView(context);
  if (v == null || !context.mounted) return;
  await runJobAction(
    context,
    ref,
    job.id,
    () => ref.read(serviceJobsApiProvider).createEvidenceRequest(job.id,
        category: v.category, prompt: v.prompt, reason: v.reason, component: v.component),
    success: 'Request sent to the owner',
  );
}

class _RequestViewDialog extends StatefulWidget {
  const _RequestViewDialog({required this.title});

  final String title;

  @override
  State<_RequestViewDialog> createState() => _RequestViewDialogState();
}

class _RequestViewDialogState extends State<_RequestViewDialog> {
  final _form = GlobalKey<FormState>();
  String _category = 'label';
  final _prompt = TextEditingController();
  final _reason = TextEditingController();
  final _component = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _category,
                decoration: const InputDecoration(labelText: 'Kind of view'),
                items: [
                  for (final c in evidenceCategories) DropdownMenuItem(value: c, child: Text(evidenceCategoryLabel(c))),
                ],
                onChanged: (v) => setState(() => _category = v ?? _category),
              ),
              TextFormField(
                controller: _prompt,
                maxLength: 500,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'What should the owner photograph?',
                  hintText: 'e.g. The pump label, without moving the pump',
                ),
                validator: (v) => v == null || v.trim().length < 3 ? 'Describe the view (at least 3 characters)' : null,
              ),
              TextFormField(
                controller: _reason,
                maxLength: 1000,
                maxLines: 2,
                decoration: const InputDecoration(labelText: 'Why it helps'),
                validator: (v) => v == null || v.trim().length < 3 ? 'Say why it helps (at least 3 characters)' : null,
              ),
              TextFormField(
                controller: _component,
                maxLength: 120,
                decoration: const InputDecoration(labelText: 'Component (optional)'),
              ),
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
                context, RequestedView(_category, _prompt.text.trim(), _reason.text.trim(), _component.text.trim()));
          },
          child: const Text('Send request'),
        ),
      ],
    );
  }
}
