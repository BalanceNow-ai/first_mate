import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/products/widgets/product_widgets.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class ProductListScreen extends ConsumerStatefulWidget {
  const ProductListScreen({super.key});

  @override
  ConsumerState<ProductListScreen> createState() => _ProductListScreenState();
}

class _ProductListScreenState extends ConsumerState<ProductListScreen> {
  late final TextEditingController _search;

  @override
  void initState() {
    super.initState();
    _search = TextEditingController(text: ref.read(productFilterProvider).search ?? '');
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _updateFilter(ProductFilter Function(ProductFilter) change) =>
      ref.read(productFilterProvider.notifier).update(change);

  void _submitSearch(String value) {
    final q = value.trim();
    _updateFilter((f) => q.isEmpty ? f.copyWith(clearSearch: true) : f.copyWith(search: q));
  }

  @override
  Widget build(BuildContext context) {
    final filter = ref.watch(productFilterProvider);
    final page = ref.watch(productListProvider);
    final categories = ref.watch(productCategoriesProvider).value ?? const <String>[];

    return Scaffold(
      appBar: AppBar(title: const Text('Shop')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
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
          const _VesselSelector(),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                FilterChip(
                  label: const Text('On sale'),
                  selected: filter.onSale,
                  onSelected: (v) => _updateFilter((f) => f.copyWith(onSale: v)),
                ),
                const SizedBox(width: 8),
                FilterChip(
                  label: const Text('In stock'),
                  selected: filter.inStockOnly,
                  onSelected: (v) => _updateFilter((f) => f.copyWith(inStockOnly: v)),
                ),
                for (final c in categories) ...[
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: Text(enumLabel(c.replaceAll('_', ' '))),
                    selected: filter.category == c,
                    onSelected: (v) => _updateFilter(
                        (f) => v ? f.copyWith(category: c) : f.copyWith(clearCategory: true)),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: page.when(
              data: (p) => _ProductGrid(page: p, onPage: (o) => _updateFilter((f) => f.copyWith(offset: o))),
              loading: () => const LoadingView(message: 'Loading products'),
              error: (e, _) => ErrorView(
                error: e,
                title: 'Could not load products',
                onRetry: () => ref.invalidate(productListProvider),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Which vessel fitment is evaluated against.
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
            DropdownMenuItem(value: v.id, child: Text(v.label, overflow: TextOverflow.ellipsis)),
          const DropdownMenuItem(
            value: none,
            child: Text('No vessel (browse everything)', overflow: TextOverflow.ellipsis),
          ),
        ],
        onChanged: (id) {
          if (id == null || id == none) {
            ref.read(useVesselFitmentProvider.notifier).set(false);
          } else {
            ref.read(useVesselFitmentProvider.notifier).set(true);
            ref.read(selectedVesselIdProvider.notifier).select(id);
          }
        },
      ),
    );
  }
}

class _ProductGrid extends StatelessWidget {
  const _ProductGrid({required this.page, required this.onPage});

  final ProductPage page;
  final ValueChanged<int> onPage;

  @override
  Widget build(BuildContext context) {
    if (page.items.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('No products match these filters.', textAlign: TextAlign.center),
        ),
      );
    }
    // Card height grows with the user's text size so nothing is clipped.
    final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
    final first = page.offset + 1;
    final last = page.offset + page.items.length;
    return CustomScrollView(
      slivers: [
        if (page.vessel != null)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            sliver: SliverToBoxAdapter(
              child: Text('Fitment checked against ${page.vessel!.label}',
                  style: Theme.of(context).textTheme.bodySmall),
            ),
          ),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          sliver: SliverGrid(
            gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 300,
              mainAxisExtent: 170 + 230 * textScale,
              crossAxisSpacing: 12,
              mainAxisSpacing: 12,
            ),
            delegate: SliverChildBuilderDelegate(
              (context, i) => ProductCard(product: page.items[i], vesselLabel: page.vessel?.label),
              childCount: page.items.length,
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Previous page',
                  onPressed: page.offset > 0
                      ? () => onPage((page.offset - page.limit).clamp(0, page.total))
                      : null,
                ),
                Text('$first–$last of ${page.total}'),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  tooltip: 'Next page',
                  onPressed: page.hasMore ? () => onPage(page.offset + page.limit) : null,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// Short vessel name for a fitment badge from the server's `nickname (…)` label.
String? vesselShortName(String? label) {
  if (label == null) return null;
  final i = label.indexOf(' (');
  return i > 0 ? label.substring(0, i) : label;
}

class ProductCard extends StatelessWidget {
  const ProductCard({super.key, required this.product, this.vesselLabel});

  final Product product;
  final String? vesselLabel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: () => context.go('/products/${product.id}'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: 150,
              child: ProductImage(url: product.primaryImage, semanticLabel: product.name),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (product.brand != null)
                      Text(product.brand!, style: theme.textTheme.labelMedium),
                    Text(
                      product.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const Spacer(),
                    if (product.fitment != null) ...[
                      FitmentBadge(
                        fitment: product.fitment!,
                        vesselName: vesselShortName(vesselLabel),
                        dense: true,
                      ),
                      const SizedBox(height: 6),
                    ],
                    PriceText(
                      effectiveCents: product.effectivePriceCents,
                      regularCents: product.priceCents,
                      onSale: product.onSale,
                      currency: product.currency,
                    ),
                    const SizedBox(height: 4),
                    StockLabel(inStock: product.inStock, quantity: product.stockQuantity),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
