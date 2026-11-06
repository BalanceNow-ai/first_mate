import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';

/// Page size of a limit/offset list (`jobs`, `inbox`, `invoices`, `directory`).
/// The defaults are the server's own defaults; tests override them.
final listPageSizeProvider = Provider.family<int, String>((ref, list) => list == 'directory' ? 20 : 50);

/// The rows of a limit/offset list loaded so far.
class Paged<T> {
  const Paged({required this.items, required this.hasMore, this.loadingMore = false, this.moreError});

  final List<T> items;

  /// The last page came back full, so the server may have more rows.
  final bool hasMore;
  final bool loadingMore;

  /// Why the last "Load more" failed (the rows already shown stay).
  final Object? moreError;

  Paged<T> copyWith({bool? loadingMore, Object? moreError}) =>
      Paged(items: items, hasMore: hasMore, loadingMore: loadingMore ?? this.loadingMore, moreError: moreError);
}

/// Loads a limit/offset list one page at a time; [loadMore] appends the next page
/// (nothing is silently cut off at the first page).
abstract class PagedNotifier<T> extends AsyncNotifier<Paged<T>> {
  /// Which page size applies (see [listPageSizeProvider]).
  String get listName;

  /// Reads one page. Subclasses `ref.watch` their API in [build] before calling super.
  Future<List<T>> fetchPage({required int offset, required int limit});

  int get _limit => ref.read(listPageSizeProvider(listName));

  @override
  Future<Paged<T>> build() async {
    final limit = _limit;
    final first = await fetchPage(offset: 0, limit: limit);
    return Paged(items: first, hasMore: first.length >= limit);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.loadingMore) return;
    state = AsyncData(current.copyWith(loadingMore: true));
    final limit = _limit;
    try {
      final next = await fetchPage(offset: current.items.length, limit: limit);
      if (!ref.mounted) return;
      state = AsyncData(Paged(items: [...current.items, ...next], hasMore: next.length >= limit));
    } catch (e) {
      if (!ref.mounted) return;
      state = AsyncData(current.copyWith(loadingMore: false, moreError: e));
    }
  }
}

/// "Load more" under a paged list: shown only while the server may have more rows.
class LoadMoreButton extends StatelessWidget {
  const LoadMoreButton({
    super.key,
    required this.hasMore,
    required this.loadingMore,
    required this.onLoadMore,
    this.error,
    this.label = 'Load more',
  });

  final bool hasMore;
  final bool loadingMore;
  final Object? error;
  final VoidCallback onLoadMore;
  final String label;

  @override
  Widget build(BuildContext context) {
    if (!hasMore) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        children: [
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('Could not load more: ${describeError(error!)}', textAlign: TextAlign.center),
            ),
          Center(
            child: loadingMore
                ? const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(strokeWidth: 2.5, semanticsLabel: 'Loading more'),
                  )
                : OutlinedButton.icon(
                    onPressed: onLoadMore,
                    icon: const Icon(Icons.expand_more),
                    label: Text(error == null ? label : 'Try again'),
                  ),
          ),
        ],
      ),
    );
  }
}
