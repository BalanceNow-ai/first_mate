import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/admin.dart';
import 'package:helm_marine/core/models/loyalty.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/admin/data/admin_api.dart';
import 'package:helm_marine/features/admin/providers/admin_providers.dart';
import 'package:helm_marine/features/content/widgets/synthetic_badge.dart';
import 'package:helm_marine/features/products/data/catalogue_api.dart';
import 'package:helm_marine/features/loyalty/screens/crew_dashboard_screen.dart' show RedemptionTile;
import 'package:intl/intl.dart';

final _when = DateFormat('d MMM y, h:mm a');

String _title(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1).replaceAll('_', ' ');

Color _statusColor(String status) => switch (status) {
      'unverified' || 'pending' || 'requested' => HelmTheme.ocean,
      'confirmed' => HelmTheme.warning,
      'verified' || 'approved' || 'admitted' || 'fulfilled' => HelmTheme.success,
      'rejected' || 'revoked' || 'cancelled' => HelmTheme.error,
      _ => HelmTheme.mutedText,
    };

/// Admin curation console. Every call needs the server-side `admin` role; the
/// server's 403 is shown as-is (the client role only hides the entry point).
class AdminConsoleScreen extends ConsumerWidget {
  const AdminConsoleScreen({super.key});

  static const tabs = [
    'Fitment rules',
    'Equipment verification',
    'Knowledge sources',
    'Experience redemptions',
    'Users & roles',
    'Audit trail',
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(currentUserProvider)?.role;
    return DefaultTabController(
      length: tabs.length,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Admin console'),
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            indicatorColor: HelmTheme.seafoam,
            tabs: [for (final t in tabs) Tab(text: t)],
          ),
        ),
        body: Column(
          children: [
            if (role != 'admin')
              const MaterialBanner(
                content: Text('Your profile does not have the admin role; the server will refuse these actions.'),
                leading: Icon(Icons.lock_outline),
                actions: [SizedBox.shrink()],
              ),
            const Expanded(
              child: TabBarView(children: [
                _FitmentTab(),
                _EquipmentTab(),
                _KnowledgeTab(),
                _RedemptionsTab(),
                _UsersTab(),
                _AuditTab(),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}

/// Runs an admin action, shows the outcome (or the server's `{detail, code}`).
Future<T?> _run<T>(BuildContext context, Future<T> Function() action, String done) async {
  try {
    final result = await action();
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
    return result;
  } catch (e) {
    if (context.mounted) {
      final api = ApiError.from(e);
      showErrorSnackBar(context, e, prefix: api == null ? null : 'Refused (${api.code})');
    }
    return null;
  }
}

/// Asks for an optional (or required) note; returns null when cancelled.
Future<String?> _noteDialog(BuildContext context, String title, String action,
    {String label = 'Note (optional)', String? body}) async {
  final controller = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (body != null) ...[Text(body), const SizedBox(height: 12)],
          TextField(
            controller: controller,
            maxLines: 3,
            maxLength: 1000,
            decoration: InputDecoration(labelText: label),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.of(context).pop(true), child: Text(action)),
      ],
    ),
  );
  final text = controller.text;
  return ok == true ? text : null;
}

class _Filters extends StatelessWidget {
  const _Filters({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: children),
      );
}

class _StatusDropdown extends StatelessWidget {
  const _StatusDropdown({required this.value, required this.options, required this.onChanged, this.label = 'Status'});

  final String value;
  final List<String> options;
  final ValueChanged<String> onChanged;
  final String label;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 200,
        child: DropdownButtonFormField<String>(
          isExpanded: true,
          initialValue: value,
          decoration: InputDecoration(labelText: label, isDense: true),
          items: [
            for (final o in options) DropdownMenuItem(value: o, child: Text(o.isEmpty ? 'All' : _title(o))),
          ],
          onChanged: (v) => onChanged(v ?? value),
        ),
      );
}

Widget _listOrState<T>(
  AsyncValue<List<T>> value, {
  required String what,
  required VoidCallback retry,
  required Widget Function(T) item,
  String? empty,
}) =>
    value.when(
      loading: () => LoadingView(message: 'Loading $what'),
      error: (e, _) => ErrorView(error: e, title: 'Could not load $what', onRetry: retry),
      data: (list) => list.isEmpty
          ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(empty ?? 'Nothing here.')))
          : ListView.builder(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              itemCount: list.length,
              itemBuilder: (context, i) => ContentWidth(maxWidth: 960, child: item(list[i])),
            ),
    );

// ------------------------------------------------------------------ fitment rules
final _productNameProvider = FutureProvider.autoDispose.family<String, String>((ref, id) async {
  final product = await ref.watch(catalogueApiProvider).getProduct(id);
  return '${product.name} (${product.sku})';
});

class _FitmentTab extends ConsumerStatefulWidget {
  const _FitmentTab();

  @override
  ConsumerState<_FitmentTab> createState() => _FitmentTabState();
}

class _FitmentTabState extends ConsumerState<_FitmentTab> {
  String _status = 'unverified';
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final rules = ref.watch(fitmentRulesProvider(_status)).whenData((list) {
      final q = _query.trim().toLowerCase();
      if (q.isEmpty) return list;
      return [
        for (final r in list)
          if ([...r.scope, r.notes ?? '', r.dataSource ?? '', r.productId].join(' ').toLowerCase().contains(q)) r,
      ];
    });
    return Column(
      children: [
        _Filters(children: [
          _StatusDropdown(
            value: _status,
            options: const ['unverified', 'verified', 'rejected'],
            onChanged: (v) => setState(() => _status = v),
          ),
          SizedBox(
            width: 280,
            child: TextField(
              decoration: const InputDecoration(labelText: 'Filter rules', prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (v) => setState(() => _query = v),
            ),
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(fitmentRulesProvider(_status)),
          ),
        ]),
        Expanded(
          child: _listOrState(
            rules,
            what: 'fitment rules',
            retry: () => ref.invalidate(fitmentRulesProvider(_status)),
            empty: 'No $_status fitment rules.',
            item: (r) => _FitmentRuleCard(rule: r, status: _status),
          ),
        ),
      ],
    );
  }
}

class _FitmentRuleCard extends ConsumerWidget {
  const _FitmentRuleCard({required this.rule, required this.status});

  final FitmentRule rule;
  final String status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = rule;
    final product = ref.watch(_productNameProvider(r.productId));
    final api = ref.read(adminApiProvider);
    void refresh() {
      for (final s in const ['unverified', 'verified', 'rejected']) {
        ref.invalidate(fitmentRulesProvider(s));
      }
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text(product.value ?? 'Product ${r.productId.substring(0, 8)}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              InfoPill(label: _title(r.verificationStatus), color: _statusColor(r.verificationStatus)),
              InfoPill(label: _title(r.fitmentType)),
            ]),
            const SizedBox(height: 4),
            for (final s in r.scope) Text(s),
            Text('Confidence ${r.confidenceScore.toStringAsFixed(2)}'
                '${r.dataSource == null ? '' : ' · source: ${r.dataSource}'}'
                ' · added ${_when.format(r.createdAt.toLocal())}'),
            if (r.sourceUrl != null) SelectableText('Evidence: ${r.sourceUrl}'),
            if (r.notes != null) Text('Notes: ${r.notes}', style: const TextStyle(color: HelmTheme.mutedText)),
            if (r.verificationStatus == 'unverified') ...[
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                FilledButton.icon(
                  icon: const Icon(Icons.verified),
                  label: const Text('Verify rule'),
                  onPressed: () async {
                    final input = await _verifyDialog(context, r);
                    if (input == null || !context.mounted) return;
                    final done = await _run(
                      context,
                      () => api.verifyFitmentRule(r.id, confidence: input.$1, notes: input.$2, sourceUrl: input.$3),
                      'Rule verified',
                    );
                    if (done != null) refresh();
                  },
                ),
                OutlinedButton.icon(
                  icon: const Icon(Icons.block),
                  label: const Text('Reject rule'),
                  onPressed: () async {
                    final note = await _noteDialog(context, 'Reject this rule?', 'Reject',
                        body: 'A rejected rule never produces a fit.');
                    if (note == null || !context.mounted) return;
                    final done = await _run(context, () => api.rejectFitmentRule(r.id, notes: note), 'Rule rejected');
                    if (done != null) refresh();
                  },
                ),
              ]),
            ],
          ],
        ),
      ),
    );
  }
}

Future<(double, String?, String?)?> _verifyDialog(BuildContext context, FitmentRule rule) async {
  final form = GlobalKey<FormState>();
  final confidence = TextEditingController(
      text: (rule.confidenceScore >= minFitmentConfidence ? rule.confidenceScore : 0.8).toStringAsFixed(2));
  final notes = TextEditingController(text: rule.notes ?? '');
  final url = TextEditingController(text: rule.sourceUrl ?? '');
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Verify fitment rule'),
      content: Form(
        key: form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Only verified rules can make a product show as fitting. '
                'Verification needs confidence of at least $minFitmentConfidence.'),
            const SizedBox(height: 12),
            TextFormField(
              controller: confidence,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Confidence (0–1)'),
              validator: (v) {
                final n = double.tryParse(v?.trim() ?? '');
                if (n == null || n < 0 || n > 1) return 'Enter a number from 0 to 1';
                if (n < minFitmentConfidence) return 'Needs at least $minFitmentConfidence to verify';
                return null;
              },
            ),
            TextFormField(controller: notes, decoration: const InputDecoration(labelText: 'Notes (optional)')),
            TextFormField(controller: url, decoration: const InputDecoration(labelText: 'Evidence URL (optional)')),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (form.currentState!.validate()) Navigator.of(context).pop(true);
          },
          child: const Text('Confirm verification'),
        ),
      ],
    ),
  );
  final result = ok == true ? (double.parse(confidence.text.trim()), notes.text, url.text) : null;
  return result;
}

// ----------------------------------------------------------- equipment verification
class _EquipmentTab extends ConsumerStatefulWidget {
  const _EquipmentTab();

  @override
  ConsumerState<_EquipmentTab> createState() => _EquipmentTabState();
}

class _EquipmentTabState extends ConsumerState<_EquipmentTab> {
  String _status = 'pending';

  @override
  Widget build(BuildContext context) {
    final requests = ref.watch(verificationRequestsProvider(_status));
    final api = ref.read(adminApiProvider);
    void refresh() {
      for (final s in const ['pending', 'approved', 'rejected', 'all']) {
        ref.invalidate(verificationRequestsProvider(s));
      }
    }

    return Column(
      children: [
        _Filters(children: [
          _StatusDropdown(
            value: _status,
            options: const ['pending', 'approved', 'rejected', 'all'],
            onChanged: (v) => setState(() => _status = v),
          ),
          IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: refresh),
        ]),
        Expanded(
          child: _listOrState(
            requests,
            what: 'verification requests',
            retry: refresh,
            empty: 'No $_status verification requests.',
            item: (r) => Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                      Text(r.vesselLabel ?? 'Vessel ${r.vesselId.substring(0, 8)}',
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                      InfoPill(label: _title(r.status), color: _statusColor(r.status)),
                    ]),
                    Text('Submitted ${_when.format(r.createdAt.toLocal())} by user ${r.userId.substring(0, 8)}'),
                    if (r.submittedNote != null) Text('Owner note: ${r.submittedNote}'),
                    if (r.evidenceUrl != null) SelectableText('Evidence: ${r.evidenceUrl}'),
                    if (r.reviewNote != null) Text('Review note: ${r.reviewNote}'),
                    if (r.equipment.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      const Text('Equipment to review', style: TextStyle(fontWeight: FontWeight.w600)),
                      for (final e in r.equipment)
                        Text('• ${e.categoryName}: ${e.description}'
                            '${e.year == null ? '' : ' (${e.year})'}'
                            '${e.serialNumber == null ? '' : ' · serial ${e.serialNumber}'}'),
                    ],
                    if (r.status == 'pending') ...[
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, children: [
                        FilledButton(
                          onPressed: () async {
                            final note = await _noteDialog(context, 'Approve this profile?', 'Approve',
                                label: 'Review note (optional)',
                                body: 'The listed equipment becomes staff-verified and the owner receives the '
                                    'profile verification bonus once.');
                            if (note == null || !context.mounted) return;
                            if (await _run(context, () => api.reviewVerification(r.id, approve: true, note: note),
                                    'Request approved') !=
                                null) {
                              refresh();
                            }
                          },
                          child: const Text('Approve'),
                        ),
                        OutlinedButton(
                          onPressed: () async {
                            final note = await _noteDialog(context, 'Reject this request?', 'Reject',
                                label: 'Review note for the owner');
                            if (note == null || !context.mounted) return;
                            if (await _run(context, () => api.reviewVerification(r.id, approve: false, note: note),
                                    'Request rejected') !=
                                null) {
                              refresh();
                            }
                          },
                          child: const Text('Reject'),
                        ),
                      ]),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------ knowledge
class _KnowledgeTab extends ConsumerWidget {
  const _KnowledgeTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sources = ref.watch(knowledgeSourcesProvider);
    return Column(
      children: [
        _Filters(children: [
          FilledButton.icon(
            icon: const Icon(Icons.upload_file),
            label: const Text('Ingest document'),
            onPressed: () => showDialog<void>(context: context, builder: (_) => const _IngestDialog()),
          ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(knowledgeSourcesProvider),
          ),
        ]),
        Expanded(
          child: _listOrState(
            sources,
            what: 'knowledge sources',
            retry: () => ref.invalidate(knowledgeSourcesProvider),
            empty: 'No knowledge sources.',
            item: (s) => _SourceCard(source: s),
          ),
        ),
      ],
    );
  }
}

class _SourceCard extends ConsumerWidget {
  const _SourceCard({required this.source});

  final KnowledgeSource source;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = source;
    final api = ref.read(adminApiProvider);
    void refresh() => ref.invalidate(knowledgeSourcesProvider);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text(s.title, style: const TextStyle(fontWeight: FontWeight.bold)),
              InfoPill(label: _title(s.admissionStatus), color: _statusColor(s.admissionStatus)),
              if (s.isSynthetic) const SyntheticBadge(label: 'Synthetic source'),
              InfoPill(
                label: s.licenceVerified ? 'Licence verified' : 'Licence not verified',
                icon: s.licenceVerified ? Icons.verified_user : Icons.gpp_maybe,
                color: s.licenceVerified ? HelmTheme.success : HelmTheme.warning,
              ),
            ]),
            const SizedBox(height: 4),
            Text([
              'Domain: ${s.domain}',
              if (s.publisher != null) s.publisher!,
              'Licence: ${s.licence}',
              'v${s.version ?? '1'}',
              '${s.chunkCount} chunks',
              if (s.embeddingModels.isNotEmpty) 'embeddings: ${s.embeddingModels.join(', ')}',
            ].join(' · ')),
            if (s.appliesTo.isNotEmpty)
              Text('Applies to: ${s.appliesTo.entries.map((e) => '${e.key}=${e.value}').join(', ')}'),
            if (s.url != null) SelectableText(s.url!),
            if (s.admittedAt != null) Text('Admitted ${_when.format(s.admittedAt!.toLocal())}'),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (s.canAdmit)
                FilledButton(
                  onPressed: () async {
                    bool? verify;
                    if (!s.licenceVerified) {
                      verify = await showDialog<bool>(
                        context: context,
                        builder: (context) => AlertDialog(
                          title: const Text('Admit source'),
                          content: Text('The licence "${s.licence}" is not marked as verified. '
                              'Only admit content whose licence you have checked.'),
                          actions: [
                            TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
                            OutlinedButton(
                                onPressed: () => Navigator.of(context).pop(false),
                                child: const Text('Admit without verifying')),
                            FilledButton(
                                onPressed: () => Navigator.of(context).pop(true),
                                child: const Text('Licence checked — admit')),
                          ],
                        ),
                      );
                      if (verify == null) return;
                    }
                    if (!context.mounted) return;
                    if (await _run(context, () => api.admit(s.id, licenceVerified: verify == true ? true : null),
                            'Source admitted') !=
                        null) {
                      refresh();
                    }
                  },
                  child: const Text('Admit'),
                ),
              if (s.canRevoke)
                OutlinedButton(
                  onPressed: () async {
                    if (await _run(context, () => api.revoke(s.id), 'Source revoked') != null) refresh();
                  },
                  child: const Text('Revoke'),
                ),
              OutlinedButton(
                onPressed: () async {
                  final r = await _run(context, () => api.reembed(s.id), 'Re-embedded');
                  if (r != null) {
                    refresh();
                    if (context.mounted) {
                      ScaffoldMessenger.of(context)
                          .showSnackBar(SnackBar(content: Text('${r.chunksEmbedded} chunks re-embedded')));
                    }
                  }
                },
                child: const Text('Re-embed'),
              ),
              TextButton(
                style: TextButton.styleFrom(foregroundColor: HelmTheme.error),
                onPressed: () async {
                  final ok = await showDialog<bool>(
                    context: context,
                    builder: (context) => AlertDialog(
                      title: const Text('Delete source?'),
                      content: Text('“${s.title}” and all of its chunks will be deleted.'),
                      actions: [
                        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
                        FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Delete')),
                      ],
                    ),
                  );
                  if (ok == true && context.mounted) {
                    final deleted = await _run(context, () async {
                      await api.deleteSource(s.id);
                      return true;
                    }, 'Source deleted');
                    if (deleted == true) refresh();
                  }
                },
                child: const Text('Delete'),
              ),
            ]),
          ],
        ),
      ),
    );
  }
}

class _IngestDialog extends ConsumerStatefulWidget {
  const _IngestDialog();

  @override
  ConsumerState<_IngestDialog> createState() => _IngestDialogState();
}

class _IngestDialogState extends ConsumerState<_IngestDialog> {
  final _form = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _publisher = TextEditingController();
  final _url = TextEditingController();
  final _licence = TextEditingController();
  final _content = TextEditingController();
  String? _domain;
  String _format = 'markdown';
  bool _licenceVerified = false;
  bool _synthetic = false;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_title, _publisher, _url, _licence, _content]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    final result = await _run(
      context,
      () => ref.read(adminApiProvider).ingest(KnowledgeIngestDraft(
            title: _title.text.trim(),
            publisher: _publisher.text.trim(),
            url: _url.text.trim(),
            licence: _licence.text.trim(),
            licenceVerified: _licenceVerified,
            domain: _domain!,
            isSynthetic: _synthetic,
            format: _format,
            content: _content.text,
          )),
      'Document ingested',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (result != null) {
      ref.invalidate(knowledgeSourcesProvider);
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Ingest ${result.status.replaceAll('_', ' ')}: ${result.source.title} is '
            '${result.source.admissionStatus} (${result.source.chunkCount} chunks)'),
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final domains = ref.watch(knowledgeDomainsProvider);
    String? required(String? v) => (v == null || v.trim().isEmpty) ? 'Required' : null;
    return AlertDialog(
      title: const Text('Ingest knowledge document'),
      content: SizedBox(
        width: 560,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('New documents are stored as pending and are never used by the First Mate until admitted.'),
                TextFormField(controller: _title, decoration: const InputDecoration(labelText: 'Title'), validator: required),
                TextFormField(controller: _publisher, decoration: const InputDecoration(labelText: 'Publisher')),
                TextFormField(controller: _url, decoration: const InputDecoration(labelText: 'Source URL')),
                TextFormField(
                    controller: _licence,
                    decoration: const InputDecoration(labelText: 'Licence (e.g. CC BY 4.0, permission reference)'),
                    validator: required),
                CheckboxListTile(
                  value: _licenceVerified,
                  onChanged: (v) => setState(() => _licenceVerified = v ?? false),
                  title: const Text('Licence verified'),
                  subtitle: const Text('Required before the source can be admitted'),
                  contentPadding: EdgeInsets.zero,
                ),
                CheckboxListTile(
                  value: _synthetic,
                  onChanged: (v) => setState(() => _synthetic = v ?? false),
                  title: const Text('Synthetic test fixture'),
                  contentPadding: EdgeInsets.zero,
                ),
                DropdownButtonFormField<String>(
          isExpanded: true,
                  initialValue: _domain,
                  decoration: const InputDecoration(labelText: 'Domain'),
                  items: [
                    for (final d in domains.value ?? const []) DropdownMenuItem(value: d.key, child: Text(d.name)),
                  ],
                  onChanged: (v) => setState(() => _domain = v),
                  validator: (v) => v == null ? 'Choose a domain' : null,
                ),
                DropdownButtonFormField<String>(
          isExpanded: true,
                  initialValue: _format,
                  decoration: const InputDecoration(labelText: 'Format'),
                  items: const [
                    DropdownMenuItem(value: 'markdown', child: Text('Markdown')),
                    DropdownMenuItem(value: 'text', child: Text('Plain text')),
                  ],
                  onChanged: (v) => setState(() => _format = v ?? 'markdown'),
                ),
                TextFormField(
                  controller: _content,
                  minLines: 6,
                  maxLines: 12,
                  decoration: const InputDecoration(labelText: 'Content', alignLabelWithHint: true),
                  validator: required,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _submit, child: const Text('Ingest')),
      ],
    );
  }
}

// ---------------------------------------------------------------- redemptions
class _RedemptionsTab extends ConsumerStatefulWidget {
  const _RedemptionsTab();

  @override
  ConsumerState<_RedemptionsTab> createState() => _RedemptionsTabState();
}

class _RedemptionsTabState extends ConsumerState<_RedemptionsTab> {
  String _status = 'requested';

  void _refresh() {
    for (final s in const ['', 'requested', 'confirmed', 'fulfilled', 'cancelled']) {
      ref.invalidate(adminRedemptionsProvider(s));
    }
  }

  Future<void> _act(Redemption r, String action, String label) async {
    final note = await _noteDialog(context, '$label ${r.experienceTitle}?', label,
        label: 'Staff note (optional)',
        body: action == 'cancel' ? '${r.pointsCost} points are restored to the customer.' : null);
    if (note == null || !mounted) return;
    if (await _run(context, () => ref.read(adminApiProvider).redemptionAction(r.id, action, staffNote: note),
            'Redemption ${action == 'fulfil' ? 'fulfilled' : '${action}ed'}') !=
        null) {
      _refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final list = ref.watch(adminRedemptionsProvider(_status));
    return Column(
      children: [
        _Filters(children: [
          _StatusDropdown(
            value: _status,
            options: const ['requested', 'confirmed', 'fulfilled', 'cancelled', ''],
            onChanged: (v) => setState(() => _status = v),
          ),
          IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: _refresh),
        ]),
        Expanded(
          child: _listOrState(
            list,
            what: 'redemptions',
            retry: _refresh,
            empty: 'No ${_status.isEmpty ? '' : '$_status '}redemptions.',
            item: (r) => Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  RedemptionTile(redemption: r),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    child: Wrap(spacing: 8, children: [
                      Text('Customer ${r.userId?.substring(0, 8) ?? ''} · provider ${r.cmsProvider}'),
                      if (r.canConfirm) FilledButton(onPressed: () => _act(r, 'confirm', 'Confirm'), child: const Text('Confirm')),
                      if (r.canFulfil) FilledButton(onPressed: () => _act(r, 'fulfil', 'Fulfil'), child: const Text('Mark fulfilled')),
                      if (r.canCancel)
                        OutlinedButton(onPressed: () => _act(r, 'cancel', 'Cancel'), child: const Text('Cancel & restore points')),
                    ]),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------- users
class _UsersTab extends ConsumerStatefulWidget {
  const _UsersTab();

  @override
  ConsumerState<_UsersTab> createState() => _UsersTabState();
}

class _UsersTabState extends ConsumerState<_UsersTab> {
  String _email = '';
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final users = ref.watch(adminUsersProvider(_email));
    final me = ref.watch(currentUserIdProvider);
    return Column(
      children: [
        _Filters(children: [
          SizedBox(
            width: 320,
            child: TextField(
              controller: _search,
              decoration: const InputDecoration(labelText: 'Search by email', prefixIcon: Icon(Icons.search), isDense: true),
              onSubmitted: (v) => setState(() => _email = v.trim()),
            ),
          ),
          FilledButton(onPressed: () => setState(() => _email = _search.text.trim()), child: const Text('Search')),
        ]),
        Expanded(
          child: _listOrState(
            users,
            what: 'users',
            retry: () => ref.invalidate(adminUsersProvider(_email)),
            empty: 'No users match.',
            item: (u) => _UserTile(user: u, isMe: u.id == me, onChanged: () => ref.invalidate(adminUsersProvider(_email))),
          ),
        ),
      ],
    );
  }
}

class _UserTile extends ConsumerWidget {
  const _UserTile({required this.user, required this.isMe, required this.onChanged});

  final User user;
  final bool isMe;
  final VoidCallback onChanged;

  static const roles = ['customer', 'operator', 'dispatcher', 'admin'];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      child: ListTile(
        title: Text(user.fullName == null ? user.email : '${user.fullName} — ${user.email}'),
        subtitle: Text('Joined ${_when.format(user.createdAt.toLocal())}${isMe ? ' · you' : ''}'),
        trailing: SizedBox(
          width: 160,
          child: DropdownButtonFormField<String>(
          isExpanded: true,
            initialValue: roles.contains(user.role) ? user.role : null,
            decoration: const InputDecoration(labelText: 'Role', isDense: true),
            items: [for (final r in roles) DropdownMenuItem(value: r, child: Text(_title(r)))],
            onChanged: (role) async {
              if (role == null || role == user.role) return;
              final ok = await showDialog<bool>(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('Change role?'),
                  content: Text('${user.email}: ${_title(user.role)} → ${_title(role)}. This is recorded in the audit trail.'),
                  actions: [
                    TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
                    FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Change role')),
                  ],
                ),
              );
              if (ok == true && context.mounted) {
                await _run(context, () => ref.read(adminApiProvider).setRole(user.id, role), 'Role updated');
              }
              // Re-read the server's state either way (e.g. a refused last-admin demotion).
              onChanged();
            },
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------- audit
class _AuditTab extends ConsumerStatefulWidget {
  const _AuditTab();

  @override
  ConsumerState<_AuditTab> createState() => _AuditTabState();
}

class _AuditTabState extends ConsumerState<_AuditTab> {
  String _type = '';

  @override
  Widget build(BuildContext context) {
    final entries = ref.watch(auditProvider(_type));
    return Column(
      children: [
        _Filters(children: [
          _StatusDropdown(
            label: 'Entity type',
            value: _type,
            options: const [
              '',
              'user',
              'product_compatibility',
              'equipment_verification_request',
              'knowledge_source',
              'experience_redemption',
              'crew',
            ],
            onChanged: (v) => setState(() => _type = v),
          ),
          IconButton(tooltip: 'Refresh', icon: const Icon(Icons.refresh), onPressed: () => ref.invalidate(auditProvider(_type))),
        ]),
        Expanded(
          child: _listOrState(
            entries,
            what: 'audit trail',
            retry: () => ref.invalidate(auditProvider(_type)),
            empty: 'No audit entries.',
            item: (a) => Card(
              child: ListTile(
                title: Text('${a.action} · ${a.entityType}'),
                subtitle: Text([
                  _when.format(a.createdAt.toLocal()),
                  if (a.actorId != null) 'by ${a.actorId!.substring(0, 8)}',
                  if (a.entityId != null) 'on ${a.entityId}',
                  if (a.detail != null && a.detail!.isNotEmpty) jsonEncode(a.detail),
                ].join('\n')),
                isThreeLine: true,
              ),
            ),
          ),
        ),
      ],
    );
  }
}
