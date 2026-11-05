import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/catalogue.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/money/money.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/products/widgets/product_widgets.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

/// Human label for a part role slug (`spark_plug` → `Spark plug`).
String partRoleLabel(String role) => enumLabel(role.replaceAll('_', ' '));

/// The shop: search, filters, the active-vessel selector with "compatible
/// only", fitment badges on every card and infinite scroll.
///
/// [initialParams] are the route's query parameters (deep links from
/// checklists: `q`, `part_role`, `compatible_only`, `vessel_id`, ...).
class ProductListScreen extends ConsumerStatefulWidget {
  const ProductListScreen({super.key, this.initialParams = const {}});

  final Map<String, String> initialParams;

  @override
  ConsumerState<ProductListScreen> createState() => _ProductListScreenState();
}

class _ProductListScreenState extends ConsumerState<ProductListScreen> {
  late final TextEditingController _search;

  @override
  void initState() {
    super.initState();
    _search = TextEditingController(text: ref.read(productQueryProvider).q ?? '');
    _applyParams(widget.initialParams);
  }

  @override
  void didUpdateWidget(ProductListScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!mapEquals(oldWidget.initialParams, widget.initialParams)) _applyParams(widget.initialParams);
  }

  static bool mapEquals(Map<String, String> a, Map<String, String> b) =>
      a.length == b.length && a.entries.every((e) => b[e.key] == e.value);

  void _applyParams(Map<String, String> params) {
    if (params.isEmpty) return;
    final query = ProductQuery.fromUri(params);
    _search.text = query.q ?? '';
    // Providers cannot change while the tree builds; apply after this frame.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final vesselId = params['vessel_id'];
      if (vesselId != null && vesselId.isNotEmpty) {
        ref.read(selectedVesselIdProvider.notifier).select(vesselId);
        ref.read(useVesselFitmentProvider.notifier).set(true);
      } else if (query.compatibleOnly) {
        ref.read(useVesselFitmentProvider.notifier).set(true);
      }
      ref.read(productQueryProvider.notifier).set(query);
    });
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _update(ProductQuery Function(ProductQuery) change) =>
      ref.read(productQueryProvider.notifier).update(change);

  void _submitSearch(String value) {
    final q = value.trim();
    _update((f) => f.copyWith(q: q.isEmpty ? null : q));
  }

  @override
  Widget build(BuildContext context) {
    final feed = ref.watch(productFeedProvider);
    final query = ref.watch(productQueryProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Shop')),
      body: FocusTraversalGroup(
        child: NotificationListener<ScrollNotification>(
          onNotification: (n) {
            if (n.metrics.axis == Axis.vertical && n.metrics.extentAfter < 600) {
              ref.read(productFeedProvider.notifier).loadMore();
            }
            return false;
          },
          child: CustomScrollView(
            slivers: [
              SliverList.list(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                    child: ContentWidth(
                      maxWidth: 1200,
                      child: TextField(
                        controller: _search,
                        textInputAction: TextInputAction.search,
                        onSubmitted: _submitSearch,
                        decoration: InputDecoration(
                          labelText: 'Search parts and equipment',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: IconButton(
                            icon: const Icon(Icons.clear),
                            tooltip: 'Clear search',
                            onPressed: () {
                              _search.clear();
                              _submitSearch('');
                            },
                          ),
                        ),
                      ),
                    ),
                  ),
                  const _VesselSelector(),
                  _FilterBar(query: query, onChange: _update),
                  const _CompatibleBanner(),
                  if (feed.value?.notice != null || (feed.value?.engine == SearchEngine.postgresFallback))
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Semantics(
                        liveRegion: true,
                        child: NoticeBox(
                          icon: Icons.info_outline,
                          color: HelmTheme.warning,
                          text:
                              feed.value!.notice ??
                              'The search index is unavailable; showing database search results.',
                        ),
                      ),
                    ),
                ],
              ),
              ...feed.when(
                data: (f) => productGridSlivers(context, ref, f),
                loading: () => const [
                  SliverFillRemaining(hasScrollBody: false, child: LoadingView(message: 'Loading products')),
                ],
                error: (e, _) => [
                  SliverFillRemaining(
                    hasScrollBody: false,
                    child: ErrorView(
                      error: e,
                      title: 'Could not load products',
                      onRetry: () => ref.invalidate(productFeedProvider),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Which vessel fitment is evaluated against (primary by default).
class _VesselSelector extends ConsumerWidget {
  const _VesselSelector();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vessels = ref.watch(vesselListProvider).value ?? const <Vessel>[];
    if (vessels.isEmpty) return const SizedBox(height: 8);
    final useFitment = ref.watch(useVesselFitmentProvider);
    final current = ref.watch(shoppingVesselProvider);
    const none = '__none__';
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: ContentWidth(
        maxWidth: 1200,
        child: DropdownButtonFormField<String>(
          key: ValueKey('vessel-${useFitment ? current?.id : none}'),
          initialValue: useFitment ? current?.id : none,
          isExpanded: true,
          decoration: const InputDecoration(
            labelText: 'Check fitment for',
            prefixIcon: Icon(Icons.directions_boat),
          ),
          items: [
            for (final v in vessels)
              DropdownMenuItem(
                value: v.id,
                child: Text('${v.label}${v.isPrimary ? ' · primary' : ''}', overflow: TextOverflow.ellipsis),
              ),
            const DropdownMenuItem(
              value: none,
              child: Text('No vessel (browse everything)', overflow: TextOverflow.ellipsis),
            ),
          ],
          onChanged: (id) {
            if (id == null || id == none) {
              ref.read(useVesselFitmentProvider.notifier).set(false);
              ref.read(productQueryProvider.notifier).update((q) => q.copyWith(compatibleOnly: false));
            } else {
              ref.read(useVesselFitmentProvider.notifier).set(true);
              ref.read(selectedVesselIdProvider.notifier).select(id);
            }
          },
        ),
      ),
    );
  }
}

/// "Compatible with `vessel`" toggle and banner (with a way to clear it).
class _CompatibleBanner extends ConsumerWidget {
  const _CompatibleBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vesselId = ref.watch(fitmentVesselIdProvider);
    final vessel = ref.watch(shoppingVesselProvider);
    final compatibleOnly = ref.watch(productQueryProvider.select((q) => q.compatibleOnly));
    void set(bool v) => ref.read(productQueryProvider.notifier).update((q) => q.copyWith(compatibleOnly: v));

    if (vesselId == null || vessel == null) {
      if (!compatibleOnly) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: NoticeBox(
          icon: Icons.directions_boat_outlined,
          color: HelmTheme.warning,
          text: 'Choose a vessel to show only compatible parts.',
          action: TextButton(onPressed: () => set(false), child: const Text('Show all')),
        ),
      );
    }
    if (!compatibleOnly) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Align(
          alignment: Alignment.centerLeft,
          child: FilterChip(
            avatar: const Icon(Icons.verified_outlined, size: 18),
            label: Text('Compatible with ${vessel.nickname} only'),
            selected: false,
            onSelected: (_) => set(true),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Semantics(
        container: true,
        liveRegion: true,
        child: NoticeBox(
          icon: Icons.verified,
          color: HelmTheme.success,
          text: 'Compatible with ${vessel.label}: showing only parts verified to fit, plus universal parts.',
          action: TextButton(onPressed: () => set(false), child: const Text('Show all products')),
        ),
      ),
    );
  }
}

class _FilterBar extends ConsumerWidget {
  const _FilterBar({required this.query, required this.onChange});

  final ProductQuery query;
  final void Function(ProductQuery Function(ProductQuery)) onChange;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final categories = ref.watch(productCategoriesProvider).value ?? const <CategoryCount>[];
    final brands = ref.watch(productBrandsProvider).value ?? const <BrandCount>[];
    final subCategories = [
      for (final c in categories)
        if (c.category == query.category) ...c.subCategories,
    ];
    final sortOptions = [
      if (query.isSearch) ProductSort.relevance,
      ProductSort.name,
      ProductSort.priceAsc,
      ProductSort.priceDesc,
      ProductSort.newest,
    ];
    final priceText = query.minPriceCents == null && query.maxPriceCents == null
        ? 'Price'
        : '${query.minPriceCents == null ? 'Any' : formatCents(query.minPriceCents!)}–'
              '${query.maxPriceCents == null ? 'any' : formatCents(query.maxPriceCents!)}';

    Widget gap() => const SizedBox(width: 8);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Row(
        children: [
          _MenuChip<String?>(
            label: query.category ?? 'Category',
            selected: query.category != null,
            tooltip: 'Filter by category',
            options: [
              const (null, 'All categories'),
              for (final c in categories) (c.category, '${c.category} (${c.count})'),
            ],
            onSelected: (v) => onChange((q) => q.copyWith(category: v, subCategory: null)),
          ),
          if (subCategories.isNotEmpty) ...[
            gap(),
            _MenuChip<String?>(
              label: query.subCategory ?? 'Sub-category',
              selected: query.subCategory != null,
              tooltip: 'Filter by sub-category',
              options: [
                const (null, 'All sub-categories'),
                for (final s in subCategories) (s.name, '${s.name} (${s.count})'),
              ],
              onSelected: (v) => onChange((q) => q.copyWith(subCategory: v)),
            ),
          ],
          gap(),
          _MenuChip<String?>(
            label: query.brand ?? 'Brand',
            selected: query.brand != null,
            tooltip: 'Filter by brand',
            options: [
              const (null, 'All brands'),
              for (final b in brands) (b.brand, '${b.brand} (${b.count})'),
            ],
            onSelected: (v) => onChange((q) => q.copyWith(brand: v)),
          ),
          gap(),
          ActionChip(
            avatar: const Icon(Icons.attach_money, size: 18),
            label: Text(priceText),
            tooltip: 'Filter by price',
            onPressed: () async {
              final range = await showDialog<(int?, int?)>(
                context: context,
                builder: (_) => _PriceDialog(min: query.minPriceCents, max: query.maxPriceCents),
              );
              if (range != null) {
                onChange((q) => q.copyWith(minPriceCents: range.$1, maxPriceCents: range.$2));
              }
            },
          ),
          gap(),
          FilterChip(
            label: const Text('On sale'),
            selected: query.onSale,
            onSelected: (v) => onChange((q) => q.copyWith(onSale: v)),
          ),
          gap(),
          FilterChip(
            label: const Text('In stock'),
            selected: query.inStock,
            onSelected: (v) => onChange((q) => q.copyWith(inStock: v)),
          ),
          if (query.partRole != null) ...[
            gap(),
            InputChip(
              label: Text('Part: ${partRoleLabel(query.partRole!)}'),
              selected: true,
              onDeleted: () => onChange((q) => q.copyWith(partRole: null)),
              deleteButtonTooltipMessage: 'Remove part filter',
            ),
          ],
          gap(),
          _MenuChip<ProductSort?>(
            label:
                'Sort: ${(query.sort ?? (query.isSearch ? ProductSort.relevance : ProductSort.name)).label}',
            selected: false,
            icon: Icons.sort,
            tooltip: 'Sort products',
            options: [for (final s in sortOptions) (s, s.label)],
            onSelected: (v) => onChange((q) => q.copyWith(sort: v)),
          ),
          if (query.hasFilters) ...[
            gap(),
            TextButton.icon(
              onPressed: () => onChange((q) => ProductQuery(q: q.q, compatibleOnly: q.compatibleOnly)),
              icon: const Icon(Icons.filter_alt_off),
              label: const Text('Clear filters'),
            ),
          ],
        ],
      ),
    );
  }
}

/// A chip that opens a menu of options.
class _MenuChip<T> extends StatelessWidget {
  const _MenuChip({
    required this.label,
    required this.selected,
    required this.options,
    required this.onSelected,
    required this.tooltip,
    this.icon = Icons.arrow_drop_down,
  });

  final String label;
  final bool selected;
  final List<(T, String)> options;
  final ValueChanged<T> onSelected;
  final String tooltip;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return MenuAnchor(
      menuChildren: [
        for (final (value, text) in options)
          MenuItemButton(onPressed: () => onSelected(value), child: Text(text)),
      ],
      builder: (context, controller, _) => InputChip(
        label: Text(label),
        avatar: Icon(icon, size: 18),
        selected: selected,
        showCheckmark: false,
        tooltip: tooltip,
        onPressed: () => controller.isOpen ? controller.close() : controller.open(),
      ),
    );
  }
}

class _PriceDialog extends StatefulWidget {
  const _PriceDialog({this.min, this.max});

  final int? min;
  final int? max;

  @override
  State<_PriceDialog> createState() => _PriceDialogState();
}

class _PriceDialogState extends State<_PriceDialog> {
  late final _min = TextEditingController(text: widget.min == null ? '' : '${widget.min! ~/ 100}');
  late final _max = TextEditingController(text: widget.max == null ? '' : '${widget.max! ~/ 100}');

  @override
  void dispose() {
    _min.dispose();
    _max.dispose();
    super.dispose();
  }

  int? _cents(TextEditingController c) {
    final v = int.tryParse(c.text.trim());
    return v == null ? null : v * 100;
  }

  @override
  Widget build(BuildContext context) {
    final digits = [FilteringTextInputFormatter.digitsOnly];
    return AlertDialog(
      title: const Text('Price range (NZD)'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _min,
            keyboardType: TextInputType.number,
            inputFormatters: digits,
            decoration: const InputDecoration(labelText: 'Minimum dollars', prefixText: r'$'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _max,
            keyboardType: TextInputType.number,
            inputFormatters: digits,
            decoration: const InputDecoration(labelText: 'Maximum dollars', prefixText: r'$'),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, (null, null)), child: const Text('Any price')),
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        TextButton(
          onPressed: () => Navigator.pop(context, (_cents(_min), _cents(_max))),
          child: const Text('Apply'),
        ),
      ],
    );
  }
}

/// The result count, product grid and "load more" footer as slivers.
List<Widget> productGridSlivers(BuildContext context, WidgetRef ref, ProductFeed feed) {
  if (feed.items.isEmpty) {
    final compatible = feed.query.compatibleOnly && feed.vessel != null;
    return [
      SliverFillRemaining(
        hasScrollBody: false,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.search_off, size: 48, color: HelmTheme.mutedText),
                const SizedBox(height: 12),
                Text(
                  compatible
                      ? 'No parts verified to fit ${feed.vessel!.label} match these filters.'
                      : 'No products match these filters.',
                  textAlign: TextAlign.center,
                ),
                if (compatible)
                  TextButton(
                    onPressed: () => ref
                        .read(productQueryProvider.notifier)
                        .update((q) => q.copyWith(compatibleOnly: false)),
                    child: const Text('Show all products'),
                  ),
              ],
            ),
          ),
        ),
      ),
    ];
  }
  final notifier = ref.read(productFeedProvider.notifier);
  // Card height grows with the user's text size so nothing is clipped.
  final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
  return [
    SliverPadding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      sliver: SliverToBoxAdapter(
        child: Semantics(
          liveRegion: true,
          child: Text(
            [
              '${feed.total} product${feed.total == 1 ? '' : 's'}',
              if (feed.vessel != null && !feed.query.compatibleOnly)
                'fitment checked against ${feed.vessel!.label}',
            ].join(' · '),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ),
    ),
    SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      sliver: SliverGrid(
        gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
          maxCrossAxisExtent: 300,
          mainAxisExtent: 150 + 230 * textScale,
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
        ),
        delegate: SliverChildBuilderDelegate(
          (context, i) => ProductCard(product: feed.items[i], vesselLabel: feed.vessel?.label),
          childCount: feed.items.length,
        ),
      ),
    ),
    SliverToBoxAdapter(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Center(
          child: _LoadMore(feed: feed, onLoadMore: notifier.loadMore),
        ),
      ),
    ),
  ];
}

class _LoadMore extends StatelessWidget {
  const _LoadMore({required this.feed, required this.onLoadMore});

  final ProductFeed feed;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    final shown = 'Showing ${feed.items.length} of ${feed.total}';
    if (feed.loadingMore) {
      return const LoadingView(message: 'Loading more products');
    }
    if (feed.loadMoreError != null) {
      return Column(
        children: [
          Text('Could not load more: ${describeError(feed.loadMoreError!)}', textAlign: TextAlign.center),
          TextButton.icon(
            onPressed: onLoadMore,
            icon: const Icon(Icons.refresh),
            label: const Text('Try again'),
          ),
        ],
      );
    }
    if (!feed.hasMore) return Text(shown, style: Theme.of(context).textTheme.bodySmall);
    return Column(
      children: [
        Text(shown, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: onLoadMore, child: const Text('Load more')),
      ],
    );
  }
}
