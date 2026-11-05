import 'package:helm_marine/core/models/json.dart';

/// `ArticleSummary` / `Article` from the content hub (`/content/articles`).
class Article {
  const Article({
    required this.id,
    required this.slug,
    required this.title,
    required this.summary,
    required this.isSynthetic,
    this.category,
    this.author,
    this.publishedAt,
    this.imageUrl,
    this.body,
  });

  final String id;
  final String slug;
  final String title;
  final String summary;
  final String? category;
  final String? author;

  /// As sent by the CMS (ISO-8601 when present).
  final String? publishedAt;
  final String? imageUrl;
  final bool isSynthetic;

  /// Markdown body (detail endpoint only).
  final String? body;

  DateTime? get publishedDate => publishedAt == null ? null : DateTime.tryParse(publishedAt!);

  factory Article.fromJson(Map<String, dynamic> json) => Article(
        id: req<String>(json, 'id'),
        slug: req<String>(json, 'slug'),
        title: req<String>(json, 'title'),
        summary: req<String>(json, 'summary'),
        category: opt<String>(json, 'category'),
        author: opt<String>(json, 'author'),
        publishedAt: opt<String>(json, 'published_at'),
        imageUrl: opt<String>(json, 'image_url'),
        isSynthetic: req<bool>(json, 'is_synthetic'),
        body: opt<String>(json, 'body'),
      );
}

/// `ArticleList`: `available: false` means the CMS is unavailable (no items).
class ArticleList {
  const ArticleList({required this.available, required this.provider, required this.items, this.reason});

  final bool available;
  final String provider;
  final List<Article> items;
  final String? reason;

  factory ArticleList.fromJson(Map<String, dynamic> json) {
    final available = req<bool>(json, 'available');
    return ArticleList(
      available: available,
      provider: req<String>(json, 'provider'),
      items: available ? [for (final a in mapList(json, 'items')) Article.fromJson(a)] : const [],
      reason: opt<String>(json, 'reason'),
    );
  }
}
