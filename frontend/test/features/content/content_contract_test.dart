// Contract: content articles parse the REAL /content/articles payload.
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/models/content.dart';

import 'engagement_test_helpers.dart';

void main() {
  test('articles from the local fixture CMS are marked synthetic', () {
    final list = ArticleList.fromJson(engMap('content_articles'));
    expect(list.available, isTrue);
    expect(list.provider, 'local_fixture');
    expect(list.items, isNotEmpty);
    expect(list.items.every((a) => a.isSynthetic && a.title.startsWith('[SYNTHETIC]')), isTrue);
    expect(list.items.first.publishedDate, isNotNull);
    expect(list.items.first.body, isNull);
  });
}
