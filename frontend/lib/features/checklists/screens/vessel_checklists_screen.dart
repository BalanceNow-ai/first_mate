import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_service.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/checklists/providers/checklist_provider.dart';

class VesselChecklistsScreen extends ConsumerStatefulWidget {
  final String vesselId;

  const VesselChecklistsScreen({super.key, required this.vesselId});

  @override
  ConsumerState<VesselChecklistsScreen> createState() =>
      _VesselChecklistsScreenState();
}

class _VesselChecklistsScreenState
    extends ConsumerState<VesselChecklistsScreen> {
  bool _generating = false;
  bool _addingToCart = false;

  Future<void> _generate() async {
    setState(() => _generating = true);
    try {
      final apiService = ref.read(apiServiceProvider);
      final result = await apiService.generateChecklists(widget.vesselId);
      ref.invalidate(vesselChecklistsProvider(widget.vesselId));
      if (mounted) {
        final linked = result['products_linked'] as int? ?? 0;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Checklists generated ($linked products linked)'),
            backgroundColor: HelmTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to generate: $e'),
            backgroundColor: HelmTheme.error,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  Future<void> _addUncheckedToCart() async {
    setState(() => _addingToCart = true);
    try {
      final apiService = ref.read(apiServiceProvider);
      final result = await apiService.addUncheckedToCart(widget.vesselId);
      if (mounted) {
        final count = result['added_count'] as int? ?? 0;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(count > 0
                ? '$count items added to cart'
                : 'No linked items to add'),
            backgroundColor: count > 0 ? HelmTheme.success : HelmTheme.accent,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed: $e'),
            backgroundColor: HelmTheme.error,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _addingToCart = false);
    }
  }

  Future<void> _toggleItem(String itemId) async {
    try {
      final apiService = ref.read(apiServiceProvider);
      await apiService.toggleChecklistItem(itemId);
      ref.invalidate(vesselChecklistsProvider(widget.vesselId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to toggle: $e')),
        );
      }
    }
  }

  Future<void> _showLinkProductDialog(String itemId, String itemName) async {
    final controller = TextEditingController();
    final apiService = ref.read(apiServiceProvider);

    final result = await showDialog<String>(
      context: context,
      builder: (context) => _LinkProductDialog(
        itemName: itemName,
        controller: controller,
        apiService: apiService,
      ),
    );

    if (result != null && mounted) {
      try {
        await apiService.linkProductToItem(itemId, result);
        ref.invalidate(vesselChecklistsProvider(widget.vesselId));
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Product linked'),
              backgroundColor: HelmTheme.success,
            ),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Failed to link: $e'),
              backgroundColor: HelmTheme.error,
            ),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final checklistsState =
        ref.watch(vesselChecklistsProvider(widget.vesselId));

    return Scaffold(
      appBar: AppBar(title: const Text('Voyage Checklists')),
      floatingActionButton: checklistsState.whenOrNull(
        data: (checklists) => checklists.isNotEmpty
            ? FloatingActionButton.extended(
                onPressed: _addingToCart ? null : _addUncheckedToCart,
                icon: _addingToCart
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.add_shopping_cart),
                label: const Text('Add Missing to Cart'),
                backgroundColor: HelmTheme.primary,
              )
            : null,
      ),
      body: checklistsState.when(
        data: (checklists) {
          if (checklists.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.checklist,
                        size: 64,
                        color: HelmTheme.primary.withOpacity(0.3)),
                    const SizedBox(height: 16),
                    Text(
                      'No checklists yet',
                      style: Theme.of(context)
                          .textTheme
                          .titleLarge
                          ?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Generate voyage checklists tailored to your vessel. '
                      'Products from the catalogue will be auto-linked where possible.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey[600]),
                    ),
                    const SizedBox(height: 24),
                    ElevatedButton.icon(
                      onPressed: _generating ? null : _generate,
                      icon: _generating
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.auto_awesome),
                      label: Text(
                          _generating ? 'Generating...' : 'Generate Checklists'),
                    ),
                  ],
                ),
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(vesselChecklistsProvider(widget.vesselId));
            },
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
              children: checklists.map((checklist) {
                final items =
                    (checklist['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
                final checkedCount =
                    items.where((i) => i['is_checked'] == true).length;

                return _ChecklistSection(
                  title: checklist['name'] as String? ?? '',
                  tier: checklist['tier'] as String? ?? '',
                  items: items,
                  checkedCount: checkedCount,
                  totalCount: items.length,
                  onToggle: _toggleItem,
                  onLinkProduct: _showLinkProductDialog,
                  onNavigateToProduct: (productId) {
                    context.go('/products/$productId');
                  },
                );
              }).toList(),
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: HelmTheme.error),
              const SizedBox(height: 16),
              Text('Failed to load checklists\n$error',
                  textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () => ref.invalidate(
                    vesselChecklistsProvider(widget.vesselId)),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ChecklistSection extends StatelessWidget {
  final String title;
  final String tier;
  final List<Map<String, dynamic>> items;
  final int checkedCount;
  final int totalCount;
  final Future<void> Function(String itemId) onToggle;
  final Future<void> Function(String itemId, String itemName) onLinkProduct;
  final void Function(String productId) onNavigateToProduct;

  const _ChecklistSection({
    required this.title,
    required this.tier,
    required this.items,
    required this.checkedCount,
    required this.totalCount,
    required this.onToggle,
    required this.onLinkProduct,
    required this.onNavigateToProduct,
  });

  IconData get _tierIcon {
    switch (tier) {
      case 'grab_and_go':
        return Icons.directions_boat;
      case 'coastal_cruising':
        return Icons.sailing;
      case 'offshore_passage':
        return Icons.explore;
      default:
        return Icons.checklist;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: ExpansionTile(
        leading: Icon(_tierIcon, color: HelmTheme.primary),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(
          '$checkedCount / $totalCount completed',
          style: TextStyle(
            color: checkedCount == totalCount
                ? HelmTheme.success
                : Colors.grey[600],
          ),
        ),
        trailing: checkedCount == totalCount
            ? const Icon(Icons.check_circle, color: HelmTheme.success)
            : null,
        children: items.map((item) {
          final itemId = item['id']?.toString() ?? '';
          final itemName = item['item_name'] as String? ?? '';
          final system = item['system'] as String? ?? '';
          final isChecked = item['is_checked'] == true;
          final productId = item['product_id']?.toString();
          final quantity = item['quantity'] as int? ?? 1;

          return _ChecklistItemTile(
            itemId: itemId,
            itemName: itemName,
            system: system,
            isChecked: isChecked,
            productId: productId,
            quantity: quantity,
            onToggle: onToggle,
            onLinkProduct: onLinkProduct,
            onNavigateToProduct: onNavigateToProduct,
          );
        }).toList(),
      ),
    );
  }
}

class _ChecklistItemTile extends StatelessWidget {
  final String itemId;
  final String itemName;
  final String system;
  final bool isChecked;
  final String? productId;
  final int quantity;
  final Future<void> Function(String) onToggle;
  final Future<void> Function(String, String) onLinkProduct;
  final void Function(String) onNavigateToProduct;

  const _ChecklistItemTile({
    required this.itemId,
    required this.itemName,
    required this.system,
    required this.isChecked,
    this.productId,
    required this.quantity,
    required this.onToggle,
    required this.onLinkProduct,
    required this.onNavigateToProduct,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Checkbox(
        value: isChecked,
        onChanged: (_) => onToggle(itemId),
        activeColor: HelmTheme.success,
      ),
      title: productId != null
          ? GestureDetector(
              onTap: () => onNavigateToProduct(productId!),
              child: Text(
                itemName,
                style: TextStyle(
                  decoration:
                      isChecked ? TextDecoration.lineThrough : null,
                  color: isChecked ? Colors.grey : HelmTheme.primary,
                  fontWeight: FontWeight.w500,
                ),
              ),
            )
          : Text(
              itemName,
              style: TextStyle(
                decoration: isChecked ? TextDecoration.lineThrough : null,
                color: isChecked ? Colors.grey : null,
              ),
            ),
      subtitle: Row(
        children: [
          Text(system, style: TextStyle(fontSize: 12, color: Colors.grey[600])),
          if (quantity > 1) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: Colors.grey[200],
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text('x$quantity',
                  style: const TextStyle(fontSize: 11)),
            ),
          ],
        ],
      ),
      trailing: productId != null
          ? Icon(Icons.link, size: 16, color: HelmTheme.success)
          : IconButton(
              icon: Icon(Icons.link_off, size: 16, color: Colors.grey[400]),
              tooltip: 'Link product',
              onPressed: () => onLinkProduct(itemId, itemName),
            ),
    );
  }
}

class _LinkProductDialog extends StatefulWidget {
  final String itemName;
  final TextEditingController controller;
  final ApiService apiService;

  const _LinkProductDialog({
    required this.itemName,
    required this.controller,
    required this.apiService,
  });

  @override
  State<_LinkProductDialog> createState() => _LinkProductDialogState();
}

class _LinkProductDialogState extends State<_LinkProductDialog> {
  List<Map<String, dynamic>> _results = [];
  bool _searching = false;

  Future<void> _search() async {
    final query = widget.controller.text.trim();
    if (query.isEmpty) return;

    setState(() => _searching = true);
    try {
      final products = await widget.apiService.getProducts(search: query, limit: 5);
      setState(() {
        _results = products
            .map((p) => {'id': p.id, 'name': p.name, 'sku': p.sku})
            .toList();
      });
    } catch (_) {
      // ignore search errors
    } finally {
      setState(() => _searching = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Link Product'),
      content: SizedBox(
        width: 320,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Find a product for: ${widget.itemName}',
              style: TextStyle(fontSize: 13, color: Colors.grey[600]),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: widget.controller,
                    decoration: const InputDecoration(
                      hintText: 'Search products...',
                      isDense: true,
                    ),
                    onSubmitted: (_) => _search(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _searching ? null : _search,
                  icon: _searching
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.search),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (_results.isNotEmpty)
              ...(_results.map((p) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(p['name'] as String, style: const TextStyle(fontSize: 13)),
                    subtitle: Text(p['sku'] as String, style: const TextStyle(fontSize: 11)),
                    onTap: () => Navigator.pop(context, p['id'] as String),
                  ))),
            if (_results.isEmpty && widget.controller.text.isNotEmpty && !_searching)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text('No products found',
                    style: TextStyle(color: Colors.grey[500])),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}
