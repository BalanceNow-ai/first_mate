import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/models/content.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/content/data/content_api.dart';
import 'package:helm_marine/features/content/widgets/synthetic_badge.dart';

/// "From The Boat Ramp" articles. Renders nothing while loading, on error, or
/// when the CMS reports itself unavailable — no placeholder content is shown.
class ArticlesSection extends ConsumerWidget {
  const ArticlesSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(articlesProvider).value;
    if (list == null || !list.available || list.items.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 24),
        Semantics(
          header: true,
          child: Text('From The Boat Ramp',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
        ),
        const SizedBox(height: 8),
        for (final a in list.items.take(4)) ArticleCard(article: a),
      ],
    );
  }
}

class ArticleCard extends StatelessWidget {
  const ArticleCard({super.key, required this.article});

  final Article article;

  @override
  Widget build(BuildContext context) {
    final a = article;
    return Card(
      child: ListTile(
        leading: const Icon(Icons.article_outlined, color: HelmTheme.ocean),
        title: Text(a.title),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(a.summary),
            const SizedBox(height: 4),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                if (a.category != null) InfoPill(label: a.category!, color: HelmTheme.ocean),
                if (a.isSynthetic) const SyntheticBadge(label: 'Synthetic sample'),
              ],
            ),
          ],
        ),
        onTap: () => context.push('/articles/${Uri.encodeComponent(a.slug)}'),
      ),
    );
  }
}
