import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Profile/menu entry for "Understand my invoice".
class InvoicesEntry extends StatelessWidget {
  const InvoicesEntry({super.key});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: ListTile(
        leading: const Icon(Icons.receipt_long_outlined),
        title: const Text('Invoices'),
        subtitle: const Text('Understand an invoice: plain-language lines, exact sums and questions'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.go('/invoices'),
      ),
    );
  }
}
