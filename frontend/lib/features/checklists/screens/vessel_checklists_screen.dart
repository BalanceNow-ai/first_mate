import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/checklist.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/checklists/data/checklist_api.dart';
import 'package:helm_marine/features/checklists/providers/checklist_provider.dart';
import 'package:helm_marine/features/products/data/catalogue_api.dart';
import 'package:helm_marine/features/products/widgets/product_widgets.dart';

/// Voyage spares checklists for one vessel: three cumulative tiers, persisted
/// ticks, product links with fitment, "add missing to cart" and exports.
class VesselChecklistsScreen extends ConsumerWidget {
  const VesselChecklistsScreen({super.key, required this.vesselId});

  final String vesselId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final set = ref.watch(checklistSetProvider(vesselId));
    final generated = set.value?.generated ?? false;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Voyage Checklists'),
        actions: [
          if (generated)
            PopupMenuButton<String>(
              tooltip: 'Checklist options',
              onSelected: (v) => v == 'regenerate' ? _regenerate(context, ref) : _deleteAll(context, ref),
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'regenerate', child: Text('Regenerate checklists')),
                PopupMenuItem(value: 'delete', child: Text('Delete all checklists')),
              ],
            ),
        ],
      ),
      body: set.when(
        loading: () => const LoadingView(message: 'Loading checklists'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load checklists',
          onRetry: () => ref.invalidate(checklistSetProvider(vesselId)),
        ),
        data: (s) => s.generated
            ? _Tiers(vesselId: vesselId, set: s)
            : _NotGenerated(vesselId: vesselId, disclaimer: s.disclaimer, vesselLabel: s.vessel.label),
      ),
    );
  }

  Future<void> _regenerate(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Regenerate checklists?'),
        content: const Text('The checklists are rebuilt from your vessel\'s current details and equipment. '
            'Items you have ticked stay ticked; products you linked yourself may be replaced.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Regenerate')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(checklistSetProvider(vesselId).notifier).generate(regenerate: true);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Checklists regenerated')));
      }
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not regenerate');
    }
  }

  Future<void> _deleteAll(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete all checklists?'),
        content: const Text('All tiers and your ticks for this vessel are deleted. You can generate them again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: HelmTheme.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(checklistSetProvider(vesselId).notifier).deleteAll();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Checklists deleted')));
      }
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not delete checklists');
    }
  }
}

/// The server's disclaimer, always visible.
class _Disclaimer extends StatelessWidget {
  const _Disclaimer({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: 'Important: $text',
      excludeSemantics: true,
      child: NoticeBox(icon: Icons.gpp_maybe_outlined, color: HelmTheme.warning, text: text),
    );
  }
}

class _NotGenerated extends ConsumerStatefulWidget {
  const _NotGenerated({required this.vesselId, required this.disclaimer, required this.vesselLabel});

  final String vesselId;
  final String disclaimer;
  final String vesselLabel;

  @override
  ConsumerState<_NotGenerated> createState() => _NotGeneratedState();
}

class _NotGeneratedState extends ConsumerState<_NotGenerated> {
  bool _busy = false;

  Future<void> _generate() async {
    setState(() => _busy = true);
    try {
      await ref.read(checklistSetProvider(widget.vesselId).notifier).generate();
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not generate checklists');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        ContentWidth(
          child: Column(
            children: [
              _Disclaimer(text: widget.disclaimer),
              const SizedBox(height: 24),
              const Icon(Icons.checklist, size: 64, color: HelmTheme.mutedText),
              const SizedBox(height: 16),
              Text('No checklists yet', style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(
                'Generate day-trip, coastal and offshore spares lists tailored to ${widget.vesselLabel}, '
                'with parts matched to your boat where fitment is verified.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              ElevatedButton.icon(
                onPressed: _busy ? null : _generate,
                icon: _busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white, semanticsLabel: 'Generating'),
                      )
                    : const Icon(Icons.auto_awesome),
                label: const Text('Generate checklists'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Tiers extends StatelessWidget {
  const _Tiers({required this.vesselId, required this.set});

  final String vesselId;
  final ChecklistSet set;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: set.tiers.length,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: ContentWidth(maxWidth: 1000, child: _Disclaimer(text: set.disclaimer)),
          ),
          TabBar(
            isScrollable: true,
            tabs: [
              for (final t in set.tiers)
                Tab(
                  child: Semantics(
                    label: '${t.tier.shortName}: ${t.checked} of ${t.total} on board',
                    excludeSemantics: true,
                    child: Text('${t.tier.shortName} ${t.checked}/${t.total}'),
                  ),
                ),
            ],
          ),
          Expanded(
            child: TabBarView(
              children: [
                for (final t in set.tiers)
                  ContentWidth(maxWidth: 1000, child: _TierView(vesselId: vesselId, tier: t, vesselLabel: set.vessel.label)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TierView extends ConsumerStatefulWidget {
  const _TierView({required this.vesselId, required this.tier, required this.vesselLabel});

  final String vesselId;
  final ChecklistTier tier;
  final String vesselLabel;

  @override
  ConsumerState<_TierView> createState() => _TierViewState();
}

class _TierViewState extends ConsumerState<_TierView> {
  bool _adding = false;
  ExportFormat? _exporting;

  ChecklistTier get tier => widget.tier;

  Future<void> _addMissing() async {
    setState(() => _adding = true);
    try {
      final result =
          await ref.read(checklistSetProvider(widget.vesselId).notifier).addMissingToCart(tier.tier);
      if (!mounted) return;
      setState(() => _adding = false);
      await showDialog<void>(context: context, builder: (_) => _AddMissingResultDialog(result: result));
    } catch (e) {
      if (mounted) {
        setState(() => _adding = false);
        showErrorSnackBar(context, e, prefix: 'Could not add to cart');
      }
    }
  }

  /// Opens the export target synchronously (inside the tap) and then fetches
  /// the export with the user's token.
  void _export(ExportFormat format) {
    final deliverer = ref.read(exportDelivererProvider);
    final target = deliverer.open(format);
    setState(() => _exporting = format);
    () async {
      try {
        final export = await ref.read(checklistApiProvider).export(widget.vesselId, tier.tier, format);
        final message = await deliverer.deliver(export, target);
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
      } catch (e) {
        target.cancel();
        if (mounted) showErrorSnackBar(context, e, prefix: 'Could not export');
      } finally {
        if (mounted) setState(() => _exporting = null);
      }
    }();
  }

  Future<void> _toggle(ChecklistItem item, bool checked) async {
    try {
      await ref.read(checklistSetProvider(widget.vesselId).notifier).setChecked(item.id, checked);
    } catch (e) {
      if (mounted) showErrorSnackBar(context, e, prefix: 'Could not update "${item.itemName}"');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final systems = <String, List<ChecklistItem>>{};
    for (final i in tier.items) {
      systems.putIfAbsent(i.system, () => []).add(i);
    }
    Widget busyIcon(IconData icon, bool busy, String label) => busy
        ? SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2, semanticsLabel: label),
          )
        : Icon(icon);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        Semantics(
          header: true,
          child: Text(tier.name, style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
        ),
        const SizedBox(height: 4),
        Text('${tier.checked} of ${tier.total} on board · ${tier.uncheckedLinked} missing item'
            '${tier.uncheckedLinked == 1 ? '' : 's'} with a linked product'),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ElevatedButton.icon(
              onPressed: _adding ? null : _addMissing,
              icon: busyIcon(Icons.add_shopping_cart, _adding, 'Adding to cart'),
              label: const Text('Add missing to cart'),
            ),
            OutlinedButton.icon(
              onPressed: _exporting != null ? null : () => _export(ExportFormat.html),
              icon: busyIcon(Icons.print_outlined, _exporting == ExportFormat.html, 'Preparing printable checklist'),
              label: const Text('Printable checklist'),
            ),
            OutlinedButton.icon(
              onPressed: _exporting != null ? null : () => _export(ExportFormat.csv),
              icon: busyIcon(Icons.download_outlined, _exporting == ExportFormat.csv, 'Preparing CSV'),
              label: const Text('Download CSV'),
            ),
          ],
        ),
        for (final entry in systems.entries) ...[
          const SizedBox(height: 20),
          Semantics(
            header: true,
            child: Text(entry.key, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
          ),
          for (final item in entry.value)
            _ItemTile(
              key: ValueKey('item-${tier.tier.wire}-${item.id}'),
              vesselId: widget.vesselId,
              item: item,
              tier: tier.tier,
              vesselLabel: widget.vesselLabel,
              onChecked: (v) => _toggle(item, v),
            ),
        ],
      ],
    );
  }
}

class _ItemTile extends ConsumerWidget {
  const _ItemTile({
    super.key,
    required this.vesselId,
    required this.item,
    required this.tier,
    required this.vesselLabel,
    required this.onChecked,
  });

  final String vesselId;
  final ChecklistItem item;
  final ChecklistTierId tier;
  final String vesselLabel;
  final ValueChanged<bool> onChecked;

  void _findPart(BuildContext context) {
    final hint = item.searchHint;
    final role = hint?.partRole ?? item.partRole;
    context.go(Uri(path: '/products', queryParameters: {
      if (role != null) 'part_role': role else 'q': hint?.q ?? item.itemName,
      'compatible_only': 'true',
      'vessel_id': hint?.vesselId ?? vesselId,
    }).toString());
  }

  Future<void> _linkWith(BuildContext context, WidgetRef ref, String productId) async {
    try {
      final updated = await ref.read(checklistSetProvider(vesselId).notifier).link(item.id, productId);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(updated.warning ?? 'Linked ${updated.product?.name ?? 'product'}'),
        backgroundColor: updated.warning == null ? null : HelmTheme.warning,
      ));
    } catch (e) {
      if (context.mounted) showErrorSnackBar(context, e, prefix: 'Not linked');
    }
  }

  Future<void> _chooseProduct(BuildContext context, WidgetRef ref) async {
    final updated = await showDialog<ChecklistItem>(
      context: context,
      builder: (_) => _LinkProductDialog(vesselId: vesselId, item: item),
    );
    if (updated != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(updated.warning ?? 'Linked ${updated.product?.name ?? 'product'}'),
        backgroundColor: updated.warning == null ? null : HelmTheme.warning,
      ));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final product = item.product;
    final inherited = item.introducedIn != tier;
    final vesselName = vesselShortName(vesselLabel);
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 8, 12, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Checkbox(
              value: item.isChecked,
              onChanged: (v) => onChecked(v ?? false),
              semanticLabel: 'On board: ${item.itemName}',
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 10),
                  Text(
                    item.itemName,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                      decoration: item.isChecked ? TextDecoration.lineThrough : null,
                    ),
                  ),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text('Qty ${item.quantity}${item.description == null ? '' : ' (${item.description})'}',
                          style: theme.textTheme.bodySmall),
                      if (inherited) _Tag('From ${item.introducedIn.shortName} kit'),
                      if (item.ifFitted) const _Tag('If fitted'),
                      if (item.isChecked) const _Tag('On board', color: HelmTheme.success),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (product != null) ...[
                    _LinkedProduct(
                      product: product,
                      fitment: item.fitment,
                      vesselName: vesselName,
                      linkStatus: item.linkStatus,
                    ),
                    if (item.warning != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: NoticeBox(icon: Icons.warning_amber, color: HelmTheme.warning, text: item.warning!),
                      ),
                    Wrap(
                      spacing: 4,
                      children: [
                        TextButton(
                          onPressed: () => _chooseProduct(context, ref),
                          child: Text('Change product', semanticsLabel: 'Change product for ${item.itemName}'),
                        ),
                      ],
                    ),
                    if (item.alternatives.isNotEmpty)
                      ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: Text('${item.alternatives.length} alternative'
                            '${item.alternatives.length == 1 ? '' : 's'}'),
                        children: [
                          for (final alt in item.alternatives)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(alt.name),
                              subtitle: Wrap(
                                spacing: 8,
                                runSpacing: 4,
                                children: [
                                  Text(alt.priceText),
                                  if (alt.fitment != null)
                                    FitmentBadge(fitment: alt.fitment!, vesselName: vesselName, dense: true),
                                  StockLabel(inStock: alt.inStock, quantity: alt.stockQuantity),
                                ],
                              ),
                              trailing: TextButton(
                                onPressed: () => _linkWith(context, ref, alt.id),
                                child: Text('Use this', semanticsLabel: 'Use ${alt.name} for ${item.itemName}'),
                              ),
                            ),
                        ],
                      ),
                  ] else ...[
                    Text('No compatible product linked yet.', style: theme.textTheme.bodySmall),
                    Wrap(
                      spacing: 4,
                      children: [
                        TextButton.icon(
                          onPressed: () => _findPart(context),
                          icon: const Icon(Icons.search),
                          label: Text('Find compatible part',
                              semanticsLabel: 'Find compatible part for ${item.itemName}'),
                        ),
                        TextButton(
                          onPressed: () => _chooseProduct(context, ref),
                          child: Text('Link a product', semanticsLabel: 'Link a product to ${item.itemName}'),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text, {this.color = HelmTheme.mutedText});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
      child: Text(text, style: TextStyle(fontSize: 12, color: HelmTheme.darken(color, 0.15))),
    );
  }
}

class _LinkedProduct extends StatelessWidget {
  const _LinkedProduct({required this.product, required this.fitment, required this.vesselName, required this.linkStatus});

  final Product product;
  final Fitment? fitment;
  final String? vesselName;
  final LinkStatus linkStatus;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          link: true,
          label: 'View ${product.name}',
          excludeSemantics: true,
          child: InkWell(
          onTap: () => context.go('/products/${product.id}'),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(product.name,
                  style: theme.textTheme.bodyMedium?.copyWith(
                      color: HelmTheme.primary, decoration: TextDecoration.underline)),
            ),
          ),
          ),
        ),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            PriceText(
              effectiveCents: product.effectivePriceCents,
              regularCents: product.priceCents,
              onSale: product.onSale,
              currency: product.currency,
            ),
            if (fitment != null) FitmentBadge(fitment: fitment!, vesselName: vesselName, dense: true),
            StockLabel(inStock: product.inStock, quantity: product.stockQuantity),
            if (linkStatus == LinkStatus.userLinkedUnverified) const _Tag('Chosen by you', color: HelmTheme.warning),
          ],
        ),
      ],
    );
  }
}

/// Lets the owner pick any product for an item. The server refuses a verified
/// mismatch (shown here) and links an unknown fit with a warning.
class _LinkProductDialog extends ConsumerStatefulWidget {
  const _LinkProductDialog({required this.vesselId, required this.item});

  final String vesselId;
  final ChecklistItem item;

  @override
  ConsumerState<_LinkProductDialog> createState() => _LinkProductDialogState();
}

class _LinkProductDialogState extends ConsumerState<_LinkProductDialog> {
  late final _search = TextEditingController();
  late bool _sameRole = widget.item.partRole != null;
  Future<List<Product>>? _results;
  String? _vesselLabel;
  String? _error;
  String? _linking;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _load() {
    final q = _search.text.trim();
    final query = ProductQuery(
      q: q.isEmpty ? null : q,
      partRole: _sameRole ? widget.item.partRole : null,
    );
    final api = ref.read(catalogueApiProvider);
    setState(() {
      _results = (query.isSearch
              ? api.search(query, vesselId: widget.vesselId, limit: 30)
              : api.listProducts(query, vesselId: widget.vesselId, limit: 30))
          .then((page) {
        _vesselLabel = page.vessel?.label;
        return page.items;
      });
    });
  }

  Future<void> _link(Product p) async {
    setState(() {
      _linking = p.id;
      _error = null;
    });
    try {
      final item = await ref.read(checklistSetProvider(widget.vesselId).notifier).link(widget.item.id, p.id);
      if (mounted) Navigator.pop(context, item);
    } catch (e) {
      final api = ApiError.from(e);
      if (mounted) {
        setState(() {
          _linking = null;
          _error = api?.code == 'fitment_mismatch'
              ? 'Not linked — ${api!.detail}. Choose a part that fits.'
              : describeError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final vesselName = vesselShortName(_vesselLabel);
    return AlertDialog(
      title: Text('Link a product to "${widget.item.itemName}"'),
      scrollable: true,
      content: SizedBox(
        width: 560,
        // Fits small phones with the keyboard open and large text.
        height: (MediaQuery.sizeOf(context).height * 0.6).clamp(280.0, 480.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _search,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _load(),
              decoration: InputDecoration(
                labelText: 'Search products',
                suffixIcon: IconButton(icon: const Icon(Icons.search), tooltip: 'Search', onPressed: _load),
              ),
            ),
            if (widget.item.partRole != null)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _sameRole,
                title: Text('Only ${widget.item.partRole!.replaceAll('_', ' ')} parts'),
                onChanged: (v) {
                  _sameRole = v ?? false;
                  _load();
                },
              ),
            const Text('Parts that do not fit your vessel cannot be linked. A part with unverified fit is '
                'linked with a warning.'),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Semantics(
                  liveRegion: true,
                  child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              ),
            const SizedBox(height: 8),
            Expanded(
              child: FutureBuilder<List<Product>>(
                future: _results,
                builder: (context, snap) {
                  if (snap.hasError) return Center(child: Text(describeError(snap.error!)));
                  if (!snap.hasData) return const LoadingView(message: 'Loading products');
                  final items = snap.data!;
                  if (items.isEmpty) return const Center(child: Text('No products found.'));
                  return ListView(
                    children: [
                      for (final p in items)
                        ListTile(
                          title: Text(p.name),
                          subtitle: Wrap(
                            spacing: 8,
                            runSpacing: 4,
                            children: [
                              Text(p.priceText),
                              if (p.fitment != null)
                                FitmentBadge(fitment: p.fitment!, vesselName: vesselName, dense: true),
                            ],
                          ),
                          trailing: _linking == p.id
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(strokeWidth: 2, semanticsLabel: 'Linking'),
                                )
                              : TextButton(
                                  onPressed: _linking != null ? null : () => _link(p),
                                  child: Text('Link', semanticsLabel: 'Link ${p.name}'),
                                ),
                        ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
    );
  }
}

class _AddMissingResultDialog extends StatelessWidget {
  const _AddMissingResultDialog({required this.result});

  final AddMissingResult result;

  @override
  Widget build(BuildContext context) {
    final r = result;
    final title = r.addedCount > 0
        ? 'Added ${r.addedCount} item${r.addedCount == 1 ? '' : 's'} to your cart'
        : r.lines.isEmpty
            ? 'Nothing to add'
            : 'Nothing new added — your cart already covers these';
    return AlertDialog(
      title: Text(title),
      scrollable: true,
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final l in r.lines)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  switch (l.status) {
                    'added' => Icons.add_shopping_cart,
                    'already_satisfied' => Icons.check_circle_outline,
                    _ => Icons.warning_amber,
                  },
                  color: switch (l.status) {
                    'added' || 'already_satisfied' => HelmTheme.success,
                    _ => HelmTheme.warning,
                  },
                ),
                title: Text(l.itemName),
                subtitle: Text([
                  l.statusLabel,
                  if (l.added > 0) 'added ${l.added}',
                  '${l.quantityInCart} of ${l.requested} in cart',
                  ?l.message,
                ].join(' · ')),
              ),
            if (r.skipped.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('Not added — no compatible product linked:', style: Theme.of(context).textTheme.titleSmall),
              for (final s in r.skipped) Text('• ${s.itemName}'),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
        TextButton(
          onPressed: () {
            final router = GoRouter.of(context);
            Navigator.pop(context);
            router.go('/cart');
          },
          child: const Text('View cart'),
        ),
      ],
    );
  }
}
