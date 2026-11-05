import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/ai_chat/widgets/answer_widgets.dart' show openExternal;
import 'package:helm_marine/features/content/data/content_api.dart';
import 'package:helm_marine/features/content/widgets/synthetic_badge.dart';
import 'package:intl/intl.dart';

/// A content hub article (`GET /content/articles/{slug}`).
class ArticleScreen extends ConsumerWidget {
  const ArticleScreen({super.key, required this.slug});

  final String slug;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final article = ref.watch(articleProvider(slug));
    return Scaffold(
      appBar: AppBar(title: const Text('The Boat Ramp')),
      body: article.when(
        loading: () => const LoadingView(message: 'Loading article'),
        error: (e, _) => ErrorView(error: e, title: 'Could not load the article', onRetry: () => ref.invalidate(articleProvider(slug))),
        data: (a) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            ContentWidth(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(header: true, child: Text(a.title, style: Theme.of(context).textTheme.headlineSmall)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 4, children: [
                    if (a.category != null) InfoPill(label: a.category!),
                    if (a.author != null) Text('By ${a.author}'),
                    if (a.publishedDate != null) Text(DateFormat('d MMM y').format(a.publishedDate!.toLocal())),
                    if (a.isSynthetic) const SyntheticBadge(label: 'Synthetic sample — not real advice'),
                  ]),
                  const SizedBox(height: 16),
                  MarkdownBody(
                    data: a.body ?? a.summary,
                    onTapLink: (text, href, title) {
                      if (href != null) openExternal(context, href);
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
