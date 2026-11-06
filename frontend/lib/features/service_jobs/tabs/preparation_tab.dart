import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/data/service_jobs_api.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/tabs/requests_tab.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

Tone itemTone(String status) => switch (status) {
      'contractor_confirmed' => Tone.good,
      'needs_evidence' => Tone.warn,
      'rejected' => Tone.bad,
      'replaced' || 'superseded' => Tone.neutral,
      _ => Tone.warn,
    };

/// The provisional preparation list: provenance, open requirements and catalogue
/// candidates with central fitment. Nothing is bought without an explicit owner tap.
class PreparationTab extends ConsumerWidget {
  const PreparationTab({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(preparationItemsProvider(job.id));
    final api = ref.read(serviceJobsApiProvider);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const InfoNote(
          'This list is provisional. A preparation item is not a purchase, quote, work instruction or approval. '
          'A photo resemblance is never a verified fit.',
        ),
        if (!job.isClosed)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              ActionButton(
                label: 'Suggest likely items',
                icon: Icons.auto_awesome_outlined,
                onPressed: () => runJobAction(context, ref, job.id, () => api.suggestPreparation(job.id),
                    success: 'Suggestions added — check each one'),
              ),
              ActionButton(
                label: 'Add an item',
                icon: Icons.add,
                onPressed: () async {
                  final input = await showDialog<PreparationItemInput>(context: context, builder: (_) => const ItemDialog());
                  if (input == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.createPreparationItem(job.id, input),
                      success: 'Item added');
                },
              ),
            ]),
          ),
        AsyncSection<List<PreparationItem>>(
          value: items,
          onRetry: () => ref.invalidate(preparationItemsProvider(job.id)),
          builder: (all) {
            final active = all.where((i) => i.isActive).toList();
            final inactive = all.where((i) => !i.isActive).toList();
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (active.isEmpty) const Text('No items yet. Tap “Suggest likely items” or add your own.'),
              for (final i in active) _ItemCard(job: job, item: i),
              if (inactive.isNotEmpty) ...[
                const SizedBox(height: 16),
                Semantics(header: true, container: true, child: const Text('Rejected, replaced or superseded', style: TextStyle(fontWeight: FontWeight.bold))),
                const SizedBox(height: 8),
                for (final i in inactive) _ItemCard(job: job, item: i),
              ],
            ]);
          },
        ),
      ],
    );
  }
}

class _ItemCard extends ConsumerWidget {
  const _ItemCard({required this.job, required this.item});

  final ServiceJob job;
  final PreparationItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final i = item;
    final owner = job.viewer.isOwner;
    final api = ref.read(serviceJobsApiProvider);
    final quantity = i.quantity == null ? 'Quantity not set' : '${i.quantity}${i.unit == null ? '' : ' ${i.unit}'}';
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: i.isActive ? null : HelmTheme.surface,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(i.name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold))),
            StatusBadge(itemStatusLabel(i.status), tone: itemTone(i.status), semanticPrefix: 'Item status'),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [
            StatusBadge(itemCategoryLabel(i.category)),
            StatusBadge(originLabel(i.origin), semanticPrefix: 'Added by'),
            ProvenanceBadge(i.requirementState),
          ]),
          const SizedBox(height: 8),
          Text(i.purpose),
          const SizedBox(height: 4),
          FactRow('Quantity', quantity),
          if (i.quantityBasis != null) FactRow('Basis', i.quantityBasis!),
          if (i.sourceNote != null) FactRow('Source', i.sourceNote!),
          for (final d in i.dependsOn)
            FactRow('Depends on', '${dimensionLabel(d.dimension)} ${d.valueText ?? ''}${d.unit == null ? '' : ' ${d.unit}'} '
                '(${provenanceLabel(d.state).toLowerCase()})'),
          if (i.confirmedAt != null)
            FactRow('Confirmed', '${formatDateTime(i.confirmedAt!)}'
                '${i.confirmedByOtherOrganization ? ' · by another organisation (names are not shared)' : ''}'),
          if (i.evidenceChangedSinceConfirmation)
            const InfoNote('Evidence changed after this was confirmed — it needs confirming again.', tone: Tone.warn),
          if (i.openRequirements.isNotEmpty) ...[
            const SizedBox(height: 6),
            const Text('Still unknown:', style: TextStyle(fontWeight: FontWeight.w600)),
            BulletList(i.openRequirements),
          ],
          const SizedBox(height: 8),
          Text(catalogueMatchLabel(i.catalogueMatch), style: const TextStyle(color: HelmTheme.mutedText)),
          if (i.confirmedProduct != null) _CandidateTile(job: job, item: i, c: i.confirmedProduct!, confirmed: true),
          for (final c in i.candidates)
            if (c.productId != i.confirmedProduct?.productId) _CandidateTile(job: job, item: i, c: c),
          Text(i.commercialNote, style: const TextStyle(fontSize: 12, color: HelmTheme.mutedText)),
          if (!owner && i.isActive && !job.isClosed) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (i.status != 'contractor_confirmed')
                ActionButton(
                  label: 'Confirm requirement',
                  icon: Icons.verified_outlined,
                  filled: true,
                  onPressed: () async {
                    final r = await showDialog<_ConfirmInput>(context: context, builder: (_) => _ConfirmItemDialog(item: i));
                    if (r == null || !context.mounted) return;
                    await runJobAction(context, ref, job.id,
                        () => api.confirmItem(job.id, i, quantity: r.quantity, unit: r.unit, quantityBasis: r.basis, note: r.note),
                        success: 'Requirement confirmed');
                  },
                ),
              ActionButton(
                label: 'Replace',
                icon: Icons.swap_horiz,
                onPressed: () async {
                  final input = await showDialog<PreparationItemInput>(
                      context: context, builder: (_) => ItemDialog(initial: i, title: 'Replace with your requirement'));
                  if (input == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.replaceItem(job.id, i, input), success: 'Item replaced');
                },
              ),
              ActionButton(
                label: 'Ask for evidence',
                icon: Icons.add_a_photo_outlined,
                onPressed: () async {
                  final v = await askForView(context, title: 'Ask the owner for evidence for this item');
                  if (v == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id,
                      () => api.requestItemEvidence(job.id, i, category: v.category, prompt: v.prompt, reason: v.reason),
                      success: 'Request sent to the owner');
                },
              ),
              ActionButton(
                label: 'Reject',
                tone: Tone.bad,
                onPressed: () async {
                  final note = await promptText(context,
                      title: 'Reject this item?', label: 'Why (optional)', required: false, confirm: 'Reject');
                  if (note == null || !context.mounted) return;
                  await runJobAction(context, ref, job.id, () => api.rejectItem(job.id, i, note: note),
                      success: 'Item rejected');
                },
              ),
            ]),
          ],
        ]),
      ),
    );
  }
}

/// Why a catalogue candidate is not offered for purchase, or null when the owner may
/// add it to the cart (stock and sale status are shown separately on the tile).
String? candidateNotBuyableReason(ServiceJob job, PreparationItem item, CatalogueCandidate c) {
  if (job.status == 'cancelled' || job.status == 'archived') {
    return 'Not offered for purchase — this job is ${jobStatusLabel(job.status).toLowerCase()}.';
  }
  if (!item.isLive) {
    return 'Not offered for purchase — this item is ${itemStatusLabel(item.status).toLowerCase()}.';
  }
  if (c.dimensionCheck.status == 'range_excludes_recorded_od') {
    return 'Not offered for purchase — its stated size does not include the recorded measurement.';
  }
  return null;
}

class _CandidateTile extends ConsumerWidget {
  const _CandidateTile({required this.job, required this.item, required this.c, this.confirmed = false});

  final ServiceJob job;
  final PreparationItem item;
  final CatalogueCandidate c;
  final bool confirmed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final owner = job.viewer.isOwner;
    final price = formatCents(c.effectivePriceCents, currency: c.currency);
    final notBuyable = candidateNotBuyableReason(job, item, c);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: confirmed ? HelmTheme.success : Colors.black12),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text('${c.name}${c.brand == null ? '' : ' · ${c.brand}'}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          Text(price, style: const TextStyle(fontWeight: FontWeight.bold)),
        ]),
        Text('SKU ${c.sku} · ${c.inStock ? 'In stock' : 'Out of stock'}${c.isActive ? '' : ' · No longer sold'}'),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          if (confirmed) const StatusBadge('Confirmed match', tone: Tone.good),
          FitmentBadge(fitment: Fitment(status: FitmentStatus.parse(c.fitmentStatus), message: c.fitmentMessage), dense: true),
          StatusBadge(dimensionCheckLabel(c.dimensionCheck.status),
              tone: c.dimensionCheck.status == 'range_excludes_recorded_od' ? Tone.bad : Tone.neutral),
        ]),
        if (c.dimensionCheck.reason != null) Text(c.dimensionCheck.reason!, style: const TextStyle(fontSize: 13)),
        if (owner && notBuyable != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(notBuyable, style: const TextStyle(fontSize: 13, color: HelmTheme.mutedText)),
          ),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (owner && notBuyable == null && c.isActive && c.inStock)
            ActionButton(
              label: 'Add to cart',
              icon: Icons.add_shopping_cart,
              onPressed: () async {
                try {
                  await ref.read(cartProvider.notifier).add(c.productId);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Added ${c.name} to your cart')));
                  }
                } catch (e) {
                  if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not add to cart');
                }
              },
            ),
          if (!owner && !confirmed && item.status == 'contractor_confirmed' && item.isActive)
            ActionButton(
              label: 'Confirm this product',
              onPressed: () => runJobAction(context, ref, job.id,
                  () => ref.read(serviceJobsApiProvider).confirmCatalogueMatch(job.id, item, c.productId),
                  success: 'Catalogue product confirmed'),
            ),
        ]),
      ]),
    );
  }
}

class _ConfirmInput {
  const _ConfirmInput(this.quantity, this.unit, this.basis, this.note);

  final String quantity;
  final String unit;
  final String basis;
  final String note;
}

class _ConfirmItemDialog extends StatefulWidget {
  const _ConfirmItemDialog({required this.item});

  final PreparationItem item;

  @override
  State<_ConfirmItemDialog> createState() => _ConfirmItemDialogState();
}

class _ConfirmItemDialogState extends State<_ConfirmItemDialog> {
  final _form = GlobalKey<FormState>();
  late final _qty = TextEditingController(text: widget.item.quantity);
  late final _unit = TextEditingController(text: widget.item.unit);
  late final _basis = TextEditingController();
  final _note = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Confirm “${widget.item.name}”'),
      content: SizedBox(
        width: 440,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Text('You confirm the requirement — not a catalogue match, stock or price. '
                  'Any quantity is yours; First Mate never invents one.'),
              TextFormField(
                controller: _qty,
                decoration: const InputDecoration(labelText: 'Quantity (optional)', hintText: 'e.g. 2 or 0.8'),
                validator: (v) => v == null || v.trim().isEmpty || RegExp(r'^\d+(\.\d{1,4})?$').hasMatch(v.trim())
                    ? null
                    : 'Use a number such as 2 or 0.8',
              ),
              TextFormField(controller: _unit, maxLength: 30, decoration: const InputDecoration(labelText: 'Unit', hintText: 'each, m')),
              TextFormField(
                controller: _basis,
                maxLength: 500,
                decoration: const InputDecoration(labelText: 'Basis for the quantity', hintText: 'e.g. one at each hose end'),
                validator: (v) => _qty.text.trim().isNotEmpty && (v == null || v.trim().isEmpty)
                    ? 'Say how you arrived at the quantity'
                    : null,
              ),
              TextFormField(controller: _note, maxLength: 1000, decoration: const InputDecoration(labelText: 'Note (optional)')),
            ]),
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (!_form.currentState!.validate()) return;
            Navigator.pop(context, _ConfirmInput(_qty.text, _unit.text, _basis.text, _note.text));
          },
          child: const Text('Confirm requirement'),
        ),
      ],
    );
  }
}

/// Add an item (owner or contractor) or replace one (contractor).
class ItemDialog extends StatefulWidget {
  const ItemDialog({super.key, this.initial, this.title = 'Add an item'});

  final PreparationItem? initial;
  final String title;

  @override
  State<ItemDialog> createState() => _ItemDialogState();
}

class _ItemDialogState extends State<ItemDialog> {
  final _form = GlobalKey<FormState>();
  late String _category = widget.initial?.category ?? 'part';
  late final _name = TextEditingController(text: widget.initial?.name);
  late final _purpose = TextEditingController(text: widget.initial?.purpose);
  late final _qty = TextEditingController(text: widget.initial?.quantity);
  late final _unit = TextEditingController(text: widget.initial?.unit);
  late final _basis = TextEditingController(text: widget.initial?.quantityBasis);
  late final _open = TextEditingController(text: widget.initial?.openRequirements.join('\n'));

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
                decoration: const InputDecoration(labelText: 'Kind'),
                items: [for (final e in itemCategoryLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                onChanged: (v) => setState(() => _category = v ?? _category),
              ),
              TextFormField(
                controller: _name,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'Name *'),
                validator: (v) => v == null || v.trim().isEmpty ? 'Name the item' : null,
              ),
              TextFormField(
                controller: _purpose,
                maxLength: 2000,
                maxLines: 2,
                decoration: const InputDecoration(labelText: 'What is it for? *'),
                validator: (v) => v == null || v.trim().isEmpty ? 'Say what it is for' : null,
              ),
              TextFormField(
                controller: _qty,
                decoration: const InputDecoration(labelText: 'Quantity (optional)'),
                validator: (v) => v == null || v.trim().isEmpty || RegExp(r'^\d+(\.\d{1,4})?$').hasMatch(v.trim())
                    ? null
                    : 'Use a number such as 2 or 0.8',
              ),
              TextFormField(controller: _unit, maxLength: 30, decoration: const InputDecoration(labelText: 'Unit (optional)')),
              TextFormField(controller: _basis, maxLength: 500, decoration: const InputDecoration(labelText: 'Basis for the quantity')),
              TextFormField(
                controller: _open,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'What is still unknown? (one per line)',
                  hintText: 'e.g. Fitting thread not confirmed',
                ),
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
              context,
              PreparationItemInput(
                category: _category,
                name: _name.text,
                purpose: _purpose.text,
                quantity: _qty.text,
                unit: _unit.text,
                quantityBasis: _basis.text,
                openRequirements: _open.text.split('\n'),
              ),
            );
          },
          child: const Text('Save item'),
        ),
      ],
    );
  }
}
