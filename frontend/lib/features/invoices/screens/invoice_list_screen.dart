import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/invoices/data/invoice_amount.dart';
import 'package:helm_marine/features/invoices/providers/invoice_providers.dart';
import 'package:helm_marine/features/invoices/widgets/invoice_badges.dart';

/// `/invoices` — the owner's invoices, newest first.
class InvoiceListScreen extends ConsumerWidget {
  const InvoiceListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final invoices = ref.watch(invoiceListProvider(null));
    return Scaffold(
      appBar: AppBar(title: const Text('Invoices')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.go('/invoices/new'),
        icon: const Icon(Icons.upload_file),
        label: const Text('Understand an invoice'),
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(invoiceListProvider(null).future),
        child: ContentWidth(
          maxWidth: 820,
          child: invoices.when(
            loading: () => const LoadingView(message: 'Loading your invoices…'),
            error: (e, _) => ErrorView(
              error: e,
              title: 'Could not load your invoices',
              onRetry: () => ref.invalidate(invoiceListProvider(null)),
            ),
            data: (items) {
              if (items.isEmpty) {
                return ListView(
                  padding: const EdgeInsets.all(24),
                  children: const [
                    Icon(Icons.receipt_long, size: 56, color: HelmTheme.mutedText),
                    SizedBox(height: 12),
                    Text('No invoices yet', textAlign: TextAlign.center),
                    SizedBox(height: 8),
                    Text(
                      'Upload a PDF or a photo of an invoice and Helm will explain each line, check the sums and '
                      'help you ask factual questions.',
                      textAlign: TextAlign.center,
                    ),
                  ],
                );
              }
              return ListView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                children: [
                  for (final inv in items)
                    Card(
                      child: ListTile(
                        minVerticalPadding: 12,
                        leading: const Icon(Icons.receipt_long),
                        title: Text(inv.title),
                        subtitle: Text([
                          if (inv.supplierName != null) inv.supplierName!,
                          if (inv.total != null) 'Total ${formatInvoiceAmount(inv.total, inv.currency)}',
                          inv.statusLabel,
                          inv.standalone ? 'Not linked to a service job' : 'Linked to a service job',
                          formatWhen(inv.createdAt),
                        ].join(' · ')),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => context.go('/invoices/${inv.id}'),
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}
