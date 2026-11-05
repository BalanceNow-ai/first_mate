import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/fitment_badge.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/cart/providers/cart_provider.dart';
import 'package:helm_marine/features/content/widgets/synthetic_badge.dart';
import 'package:url_launcher/url_launcher.dart';

final _citationMarker = RegExp(r'(?<!\\)\[(\d+)\](?!\()');
final _listItem = RegExp(r'^\s*([-*+]|\d+\.)\s');

/// Prepares answer markdown: single line breaks between a heading-like line and
/// a list become paragraph breaks, and `[n]` markers that match a citation
/// become `cite:n` links (others are escaped so they render literally).
String answerMarkdown(String content, Set<int> citationIndexes) {
  final lines = content.split('\n');
  final buffer = StringBuffer();
  for (var i = 0; i < lines.length; i++) {
    final line = lines[i];
    buffer.write(line);
    if (i == lines.length - 1) break;
    final next = lines[i + 1];
    final bothList = _listItem.hasMatch(line) && _listItem.hasMatch(next);
    final blank = line.trim().isEmpty || next.trim().isEmpty;
    buffer.write(bothList || blank ? '\n' : '\n\n');
  }
  return buffer.toString().replaceAllMapped(_citationMarker, (m) {
    final n = int.parse(m[1]!);
    return citationIndexes.contains(n) ? '[\\[$n\\]](cite:$n)' : '\\[$n\\]';
  });
}

/// "Kahawai (2021 Stabicraft …)" → "Kahawai".
String vesselNickname(String label) {
  final i = label.indexOf(' (');
  return i > 0 ? label.substring(0, i) : label;
}

Future<void> openExternal(BuildContext context, String url) async {
  final uri = Uri.tryParse(url);
  final ok = uri != null && (uri.scheme == 'https' || uri.scheme == 'http') &&
      await launchUrl(uri, mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Could not open $url')));
  }
}

/// Shows that answers come from the local, deterministic test assistant.
class LocalAssistantBadge extends StatelessWidget {
  const LocalAssistantBadge({super.key});

  @override
  Widget build(BuildContext context) => const InfoPill(
        label: 'Local test assistant',
        icon: Icons.developer_mode,
        color: HelmTheme.ocean,
        tooltip: 'Answered by the local extractive test assistant over the admitted corpus — '
            'not a production AI model.',
      );
}

/// The grounding status of an answer.
class GroundingBanner extends StatelessWidget {
  const GroundingBanner({super.key, required this.grounding});

  final Grounding grounding;

  @override
  Widget build(BuildContext context) {
    final (String title, Color color, IconData icon) = switch (grounding.status) {
      GroundingStatus.grounded => ('Grounded in admitted sources', HelmTheme.success, Icons.verified_outlined),
      GroundingStatus.insufficientEvidence => (
          'No verified source — the First Mate asked a clarifying question',
          HelmTheme.warning,
          Icons.help_outline,
        ),
      GroundingStatus.conflicting => ('Sources disagree', HelmTheme.error, Icons.compare_arrows),
    };
    return Semantics(
      container: true,
      label: '$title. ${grounding.note}',
      excludeSemantics: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border(left: BorderSide(color: color, width: 4)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: HelmTheme.darken(color, 0.1), size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: TextStyle(fontWeight: FontWeight.w700, color: HelmTheme.darken(color, 0.15))),
                  if (grounding.note.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(grounding.note, style: Theme.of(context).textTheme.bodySmall),
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

/// The answer body with tappable `[n]` citation markers.
class AnswerBody extends StatelessWidget {
  const AnswerBody({super.key, required this.content, required this.citations});

  final String content;
  final List<Citation> citations;

  @override
  Widget build(BuildContext context) {
    final byIndex = {for (final c in citations) c.index: c};
    return MarkdownBody(
      data: answerMarkdown(content, byIndex.keys.toSet()),
      selectable: false,
      onTapLink: (text, href, title) {
        if (href == null) return;
        if (href.startsWith('cite:')) {
          final c = byIndex[int.tryParse(href.substring(5))];
          if (c != null) showCitation(context, c);
        } else {
          openExternal(context, href);
        }
      },
    );
  }
}

/// Bottom sheet with a citation's excerpt and provenance.
Future<void> showCitation(BuildContext context, Citation c) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Semantics(
                header: true,
                child: Text('[${c.index}] ${c.title}', style: Theme.of(context).textTheme.titleMedium),
              ),
              const SizedBox(height: 8),
              _SourceMeta(citation: c),
              const SizedBox(height: 12),
              Text('“${c.excerpt}”', style: const TextStyle(fontStyle: FontStyle.italic)),
              const SizedBox(height: 16),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close')),
              ),
            ],
          ),
        ),
      ),
    );

class _SourceMeta extends StatelessWidget {
  const _SourceMeta({required this.citation});

  final Citation citation;

  @override
  Widget build(BuildContext context) {
    final c = citation;
    return Wrap(
      spacing: 8,
      runSpacing: 4,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (c.publisher != null) Text(c.publisher!, style: Theme.of(context).textTheme.bodySmall),
        Text('Licence: ${c.licence}', style: Theme.of(context).textTheme.bodySmall),
        if (c.isSynthetic) const SyntheticBadge(label: 'Synthetic test source'),
        if (c.url != null)
          TextButton.icon(
            onPressed: () => openExternal(context, c.url!),
            icon: const Icon(Icons.open_in_new, size: 16),
            label: const Text('Open source'),
          ),
      ],
    );
  }
}

/// The numbered sources an answer cites.
class SourcesList extends StatelessWidget {
  const SourcesList({super.key, required this.citations});

  final List<Citation> citations;

  @override
  Widget build(BuildContext context) {
    if (citations.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          header: true,
          child: Text('Sources', style: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.bold)),
        ),
        const SizedBox(height: 4),
        for (final c in citations)
          InkWell(
            onTap: () => showCitation(context, c),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 32,
                    child: Text('[${c.index}]', style: const TextStyle(fontWeight: FontWeight.bold)),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(c.title, style: const TextStyle(fontWeight: FontWeight.w600)),
                        _SourceMeta(citation: c),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

/// A product the First Mate referenced, with the server's fitment verdict.
class ProductReferenceCard extends StatelessWidget {
  const ProductReferenceCard({super.key, required this.product, this.vesselLabel});

  final ProductReference product;
  final String? vesselLabel;

  @override
  Widget build(BuildContext context) {
    final p = product;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => context.push('/products/${p.id}'),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              const Icon(Icons.inventory_2_outlined, color: HelmTheme.ocean),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(p.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text(
                      [p.sku, if (p.brand != null) p.brand!, p.priceText, p.inStock ? 'In stock' : 'Out of stock']
                          .join(' · '),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 6),
                    FitmentBadge(
                      fitment: p.fitment,
                      vesselName: vesselLabel == null ? null : vesselNickname(vesselLabel!),
                      dense: true,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}

/// An explicit "Add to cart" proposal: nothing is added until it is tapped, and
/// then only through the normal `POST /cart/items` (with its server checks).
class CartActionButton extends ConsumerStatefulWidget {
  const CartActionButton({super.key, required this.action});

  final CartAction action;

  @override
  ConsumerState<CartActionButton> createState() => _CartActionButtonState();
}

class _CartActionButtonState extends ConsumerState<CartActionButton> {
  bool _busy = false;
  bool _added = false;
  Object? _error;

  Future<void> _add() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(cartProvider.notifier).add(widget.action.productId, quantity: widget.action.quantity);
      if (!mounted) return;
      setState(() => _added = true);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('Added to cart'),
        persist: false,
        action: SnackBarAction(label: 'View cart', onPressed: () => context.go('/cart')),
      ));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
      showErrorSnackBar(context, e, prefix: 'Could not add to cart');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.action.label, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 4),
          FilledButton.icon(
            onPressed: _busy || _added ? null : _add,
            icon: _busy
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : Icon(_added ? Icons.check : Icons.add_shopping_cart),
            // The spoken name says which product the action adds.
            label: Text(
              _added ? 'Added to cart' : 'Add to cart',
              semanticsLabel: _added ? 'Added to cart' : 'Add to cart: ${widget.action.label}',
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(describeError(_error!), style: const TextStyle(color: HelmTheme.error)),
            ),
        ],
      ),
    );
  }
}

/// A complete assistant answer.
class AssistantAnswer extends StatelessWidget {
  const AssistantAnswer({super.key, required this.turn});

  final AssistantTurn turn;

  @override
  Widget build(BuildContext context) {
    final grounding = turn.grounding;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            const Text('First Mate', style: TextStyle(fontWeight: FontWeight.bold, color: HelmTheme.navy)),
            if (turn.isLocalTestAssistant) const LocalAssistantBadge(),
            if (turn.vessel != null)
              InfoPill(label: 'For ${turn.vessel!.label}', icon: Icons.directions_boat_outlined, color: HelmTheme.ocean),
          ],
        ),
        const SizedBox(height: 8),
        if (grounding != null) ...[GroundingBanner(grounding: grounding), const SizedBox(height: 8)],
        AnswerBody(content: turn.content, citations: turn.citations),
        if (turn.citations.isNotEmpty) ...[const SizedBox(height: 12), SourcesList(citations: turn.citations)],
        if (turn.products.isNotEmpty) ...[
          const SizedBox(height: 12),
          Semantics(
            header: true,
            child: Text('Products', style: Theme.of(context).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.bold)),
          ),
          for (final p in turn.products) ProductReferenceCard(product: p, vesselLabel: turn.vessel?.label),
        ],
        if (turn.actions.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final a in turn.actions) CartActionButton(action: a),
        ],
      ],
    );
  }
}
