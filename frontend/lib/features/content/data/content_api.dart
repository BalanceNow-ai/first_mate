import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/content.dart';

final contentApiProvider = Provider<ContentApi>((ref) => ContentApi(ref.watch(dioProvider)));

/// Content hub articles (`/content/articles`, public).
class ContentApi {
  ContentApi(this._dio);

  final Dio _dio;

  Future<T> _call<T>(Future<Response<dynamic>> Function() send, T Function(dynamic) parse) async {
    try {
      return parse((await send()).data);
    } on DioException catch (e) {
      throw ApiError.from(e)!;
    }
  }

  Future<ArticleList> articles({String? category}) => _call(
        () => _dio.get('/content/articles', queryParameters: {'category': ?category}),
        (d) => ArticleList.fromJson((d as Map).cast<String, dynamic>()),
      );

  Future<Article> article(String slug) => _call(
        () => _dio.get('/content/articles/${Uri.encodeComponent(slug)}'),
        (d) => Article.fromJson((d as Map).cast<String, dynamic>()),
      );
}

/// The article list (hidden by callers when the CMS is unavailable).
final articlesProvider = FutureProvider.autoDispose<ArticleList>((ref) => ref.watch(contentApiProvider).articles());

final articleProvider =
    FutureProvider.autoDispose.family<Article, String>((ref, slug) => ref.watch(contentApiProvider).article(slug));
