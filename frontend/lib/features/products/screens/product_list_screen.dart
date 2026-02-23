import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/products/providers/product_provider.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';

class ProductListScreen extends ConsumerStatefulWidget {
  const ProductListScreen({super.key});

  @override
  ConsumerState<ProductListScreen> createState() => _ProductListScreenState();
}

class _ProductListScreenState extends ConsumerState<ProductListScreen> {
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _onSearch(String query) {
    ref.read(productFilterProvider.notifier).state =
        ref.read(productFilterProvider).copyWith(
              search: query.isEmpty ? null : query,
              clearSearch: query.isEmpty,
              offset: 0,
            );
  }

  @override
  Widget build(BuildContext context) {
    final productsState = ref.watch(productListProvider);
    final filter = ref.watch(productFilterProvider);
    final categoriesState = ref.watch(productCategoriesProvider);
    final brandsState = ref.watch(productBrandsProvider);
    final vesselsState = ref.watch(vesselListProvider);

    final primaryVessel = vesselsState.valueOrNull
        ?.where((v) => v.isPrimary)
        .firstOrNull;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Products'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(
              controller: _searchController,
              onSubmitted: _onSearch,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Search marine parts...',
                hintStyle: TextStyle(color: Colors.white.withOpacity(0.7)),
                prefixIcon:
                    Icon(Icons.search, color: Colors.white.withOpacity(0.7)),
                suffixIcon: _searchController.text.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear, color: Colors.white70),
                        tooltip: 'Clear search',
                        onPressed: () {
                          _searchController.clear();
                          _onSearch('');
                        },
                      )
                    : null,
                filled: true,
                fillColor: Colors.white.withOpacity(0.15),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 0),
              ),
            ),
          ),
        ),
      ),
      body: Column(
        children: [
          // Filter bar
          _FilterBar(
            filter: filter,
            categories: categoriesState.valueOrNull ?? [],
            brands: brandsState.valueOrNull ?? [],
            hasPrimaryVessel: primaryVessel != null,
            primaryVesselId: primaryVessel?.id,
            onFilterChanged: (newFilter) {
              ref.read(productFilterProvider.notifier).state = newFilter;
            },
          ),

          // Product grid
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(productListProvider);
                ref.invalidate(productCategoriesProvider);
                ref.invalidate(productBrandsProvider);
              },
              child: productsState.when(
                data: (products) {
                  if (products.isEmpty) {
                    return Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.search_off,
                              size: 64, color: Colors.grey[300]),
                          const SizedBox(height: 16),
                          const Text('No products found'),
                          const SizedBox(height: 8),
                          Text(
                            'Try adjusting your search or filters',
                            style: TextStyle(color: Colors.grey[600]),
                          ),
                        ],
                      ),
                    );
                  }

                  return GridView.builder(
                    padding: const EdgeInsets.all(16),
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      childAspectRatio: 0.7,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                    ),
                    itemCount: products.length,
                    itemBuilder: (context, index) {
                      final product = products[index];
                      return Card(
                        clipBehavior: Clip.antiAlias,
                        child: InkWell(
                          onTap: () =>
                              context.go('/products/${product.id}'),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                flex: 3,
                                child: Container(
                                  width: double.infinity,
                                  color: Colors.grey[100],
                                  child: product.imageUrl != null
                                      ? CachedNetworkImage(
                                          imageUrl: product.imageUrl!,
                                          fit: BoxFit.cover,
                                          errorWidget: (_, __, ___) =>
                                              const Icon(
                                            Icons.image_not_supported,
                                            size: 40,
                                            color: Colors.grey,
                                          ),
                                        )
                                      : const Icon(
                                          Icons.inventory_2_outlined,
                                          size: 40,
                                          color: Colors.grey,
                                        ),
                                ),
                              ),
                              Expanded(
                                flex: 2,
                                child: Padding(
                                  padding: const EdgeInsets.all(8),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      if (product.brand != null)
                                        Text(
                                          product.brand!,
                                          style: TextStyle(
                                            fontSize: 11,
                                            color: Colors.grey[600],
                                          ),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      const SizedBox(height: 2),
                                      Text(
                                        product.name,
                                        style: const TextStyle(
                                          fontSize: 13,
                                          fontWeight: FontWeight.w600,
                                        ),
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                      const Spacer(),
                                      Row(
                                        children: [
                                          if (product.isOnSale) ...[
                                            Text(
                                              '\$${product.price.toStringAsFixed(2)}',
                                              style: TextStyle(
                                                fontSize: 12,
                                                color: Colors.grey[500],
                                                decoration: TextDecoration
                                                    .lineThrough,
                                              ),
                                            ),
                                            const SizedBox(width: 4),
                                          ],
                                          Text(
                                            '\$${product.effectivePrice.toStringAsFixed(2)}',
                                            style: TextStyle(
                                              fontSize: 14,
                                              fontWeight: FontWeight.bold,
                                              color: product.isOnSale
                                                  ? HelmTheme.error
                                                  : HelmTheme.primary,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  );
                },
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (error, _) => Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.error_outline,
                          size: 48, color: HelmTheme.error),
                      const SizedBox(height: 16),
                      Text('Failed to load products\n$error',
                          textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: () =>
                            ref.invalidate(productListProvider),
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterBar extends StatelessWidget {
  final ProductFilter filter;
  final List<String> categories;
  final List<String> brands;
  final bool hasPrimaryVessel;
  final String? primaryVesselId;
  final ValueChanged<ProductFilter> onFilterChanged;

  const _FilterBar({
    required this.filter,
    required this.categories,
    required this.brands,
    required this.hasPrimaryVessel,
    this.primaryVesselId,
    required this.onFilterChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.05),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            // Category dropdown
            _FilterDropdown(
              label: 'Category',
              value: filter.category,
              items: categories,
              onChanged: (value) {
                onFilterChanged(filter.copyWith(
                  category: value,
                  clearCategory: value == null,
                  offset: 0,
                ));
              },
            ),
            const SizedBox(width: 8),

            // Brand dropdown
            _FilterDropdown(
              label: 'Brand',
              value: filter.brand,
              items: brands,
              onChanged: (value) {
                onFilterChanged(filter.copyWith(
                  brand: value,
                  clearBrand: value == null,
                  offset: 0,
                ));
              },
            ),
            const SizedBox(width: 8),

            // On Sale toggle
            FilterChip(
              label: const Text('On Sale'),
              selected: filter.onSale,
              onSelected: (selected) {
                onFilterChanged(filter.copyWith(onSale: selected, offset: 0));
              },
              selectedColor: HelmTheme.error.withOpacity(0.15),
              checkmarkColor: HelmTheme.error,
            ),

            // Vessel compatible toggle (only if user has a primary vessel)
            if (hasPrimaryVessel) ...[
              const SizedBox(width: 8),
              FilterChip(
                label: const Text('Fits My Vessel'),
                selected: filter.vesselCompatible,
                onSelected: (selected) {
                  onFilterChanged(filter.copyWith(
                    vesselCompatible: selected,
                    vesselId: selected ? primaryVesselId : null,
                    offset: 0,
                  ));
                },
                selectedColor: HelmTheme.success.withOpacity(0.15),
                checkmarkColor: HelmTheme.success,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _FilterDropdown extends StatelessWidget {
  final String label;
  final String? value;
  final List<String> items;
  final ValueChanged<String?> onChanged;

  const _FilterDropdown({
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey[300]!),
        borderRadius: BorderRadius.circular(20),
        color: value != null ? HelmTheme.primary.withOpacity(0.08) : null,
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String?>(
          value: value,
          hint: Text(label, style: const TextStyle(fontSize: 13)),
          isDense: true,
          icon: const Icon(Icons.arrow_drop_down, size: 18),
          style: const TextStyle(fontSize: 13, color: Colors.black87),
          items: [
            DropdownMenuItem<String?>(
              value: null,
              child: Text('All $label'),
            ),
            ...items.map((item) => DropdownMenuItem(
                  value: item,
                  child: Text(item),
                )),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}
