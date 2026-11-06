import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';
import 'package:url_launcher/url_launcher.dart';

/// One place on the document a value was read from.
class DocumentHighlight {
  const DocumentHighlight({required this.key, required this.label, required this.page, required this.region});

  /// `field:<name>` or `line:<id>`.
  final String key;
  final String label;
  final int? page;
  final InvoiceRegion region;
}

/// Metadata of a private document (type, size, pages) — never a storage path.
final serviceAssetProvider = FutureProvider.autoDispose.family<ServiceAsset, String>((ref, assetId) {
  return ref.watch(invoicesApiProvider).asset(assetId);
});

/// The metadata-stripped image bytes behind a short-lived signed link (a
/// server-relative link — local storage — is resolved against the API origin).
final documentImageBytesProvider = FutureProvider.autoDispose.family<Uint8List, String>((ref, assetId) async {
  final api = ref.watch(invoicesApiProvider);
  final fetch = ref.watch(documentBytesFetcherProvider);
  final link = await api.downloadUrl(assetId);
  return fetch(api.resolve(link.url).toString());
});

/// Opens a document link in a new tab/app; false when nothing could open it.
typedef DocumentLinkOpener = Future<bool> Function(Uri uri);

final documentLinkOpenerProvider = Provider<DocumentLinkOpener>(
    (ref) => (uri) => launchUrl(uri, mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank'));

/// Opens a freshly signed link in a new tab/app (links expire within minutes,
/// so one is requested on every tap). A server-relative link is resolved
/// against the API origin first.
Future<void> openDocumentLink(BuildContext context, WidgetRef ref, Future<DownloadLink> Function(InvoicesApi api) getLink) async {
  final messenger = ScaffoldMessenger.of(context);
  final api = ref.read(invoicesApiProvider);
  final open = ref.read(documentLinkOpenerProvider);
  try {
    final link = await getLink(api);
    final ok = await open(api.resolve(link.url));
    if (!ok) throw const ApiError(statusCode: null, code: 'open_failed', detail: 'The document could not be opened.');
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(describeError(e)), backgroundColor: HelmTheme.error));
  }
}

/// The invoice document beside the editable values: images render with the
/// value regions highlighted; PDFs show a page map of the regions with page
/// references and open in the browser/viewer.
class InvoiceDocumentViewer extends ConsumerWidget {
  const InvoiceDocumentViewer({
    super.key,
    required this.assetId,
    required this.highlights,
    this.selectedKey,
    this.onSelect,
  });

  final String assetId;
  final List<DocumentHighlight> highlights;
  final String? selectedKey;
  final ValueChanged<String>? onSelect;

  DocumentHighlight? get _selected {
    for (final h in highlights) {
      if (h.key == selectedKey) return h;
    }
    return null;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asset = ref.watch(serviceAssetProvider(assetId));
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: asset.when(
          loading: () => const SizedBox(height: 200, child: Center(child: CircularProgressIndicator())),
          error: (e, _) => _LoadError(error: e, onRetry: () => ref.invalidate(serviceAssetProvider(assetId))),
          data: (a) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _DocumentHeader(asset: a, onOpen: () => openDocumentLink(context, ref, (api) => api.downloadUrl(assetId))),
              const SizedBox(height: 8),
              if (_selected != null)
                Semantics(
                  liveRegion: true,
                  child: Text(
                    'Highlighted: ${_selected!.label} — ${_selected!.region.describe(_selected!.page)}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
                  ),
                )
              else
                Text('Select a value to see where it is on the document.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText)),
              const SizedBox(height: 8),
              if (a.isImage)
                _ImageWithRegions(asset: a, highlights: highlights, selectedKey: selectedKey, onSelect: onSelect)
              else
                _PageMap(asset: a, highlights: highlights, selectedKey: selectedKey, onSelect: onSelect),
            ],
          ),
        ),
      ),
    );
  }
}

class _DocumentHeader extends StatelessWidget {
  const _DocumentHeader({required this.asset, required this.onOpen});

  final ServiceAsset asset;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final kind = asset.isPdf ? 'PDF' : (asset.isImage ? 'Photo' : 'Document');
    final pages = asset.pages == null ? '' : ' · ${asset.pages} ${asset.pages == 1 ? 'page' : 'pages'}';
    return Row(
      children: [
        Icon(asset.isPdf ? Icons.picture_as_pdf_outlined : Icons.image_outlined, color: HelmTheme.ocean),
        const SizedBox(width: 8),
        Expanded(child: Text('Invoice document ($kind$pages)', style: Theme.of(context).textTheme.titleSmall)),
        if (asset.isAvailable)
          TextButton.icon(
            onPressed: onOpen,
            icon: const Icon(Icons.open_in_new, size: 18),
            label: const Text('Open the document'),
          ),
      ],
    );
  }
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.error_outline, color: HelmTheme.error),
      title: const Text('Could not load the document'),
      subtitle: Text(describeError(error)),
      trailing: TextButton(onPressed: onRetry, child: const Text('Retry')),
    );
  }
}

class _RegionBox extends StatelessWidget {
  const _RegionBox({required this.highlight, required this.selected, required this.onTap});

  final DocumentHighlight highlight;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? HelmTheme.coral : HelmTheme.ocean;
    return Semantics(
      button: onTap != null,
      selected: selected,
      label: '${highlight.label}, ${highlight.region.describe(highlight.page)}',
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: color.withValues(alpha: selected ? 0.28 : 0.08),
            border: Border.all(color: color, width: selected ? 2.5 : 1),
          ),
        ),
      ),
    );
  }
}

List<Widget> _regionLayer(
  BoxConstraints box,
  List<DocumentHighlight> highlights,
  String? selectedKey,
  ValueChanged<String>? onSelect, {
  int page = 1,
}) {
  final ordered = [
    for (final h in highlights)
      if ((h.page ?? 1) == page && h.key != selectedKey) h,
    for (final h in highlights)
      if ((h.page ?? 1) == page && h.key == selectedKey) h,
  ];
  return [
    for (final h in ordered)
      Positioned(
        left: h.region.x * box.maxWidth,
        top: h.region.y * box.maxHeight,
        width: (h.region.w * box.maxWidth).clamp(4.0, box.maxWidth),
        height: (h.region.h * box.maxHeight).clamp(4.0, box.maxHeight),
        child: _RegionBox(
          highlight: h,
          selected: h.key == selectedKey,
          onTap: onSelect == null ? null : () => onSelect(h.key),
        ),
      ),
  ];
}

class _ImageWithRegions extends ConsumerWidget {
  const _ImageWithRegions({required this.asset, required this.highlights, this.selectedKey, this.onSelect});

  final ServiceAsset asset;
  final List<DocumentHighlight> highlights;
  final String? selectedKey;
  final ValueChanged<String>? onSelect;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bytes = ref.watch(documentImageBytesProvider(asset.id));
    final ratio = (asset.width != null && asset.height != null && asset.height! > 0)
        ? asset.width! / asset.height!
        : 3 / 4;
    return bytes.when(
      loading: () => AspectRatio(aspectRatio: ratio, child: const Center(child: CircularProgressIndicator())),
      error: (e, _) => _LoadError(error: e, onRetry: () => ref.invalidate(documentImageBytesProvider(asset.id))),
      data: (data) => AspectRatio(
        aspectRatio: ratio,
        child: LayoutBuilder(
          builder: (context, box) => Stack(
            children: [
              Positioned.fill(
                child: Image.memory(
                  data,
                  fit: BoxFit.fill,
                  semanticLabel: 'Photo of the invoice with ${highlights.length} highlighted '
                      '${highlights.length == 1 ? 'area' : 'areas'}',
                  errorBuilder: (context, _, _) => const Center(child: Text('This image could not be shown.')),
                ),
              ),
              ..._regionLayer(box, highlights, selectedKey, onSelect),
            ],
          ),
        ),
      ),
    );
  }
}

/// A page-shaped map of where each value sits on a PDF page (positions only).
class _PageMap extends StatelessWidget {
  const _PageMap({required this.asset, required this.highlights, this.selectedKey, this.onSelect});

  final ServiceAsset asset;
  final List<DocumentHighlight> highlights;
  final String? selectedKey;
  final ValueChanged<String>? onSelect;

  @override
  Widget build(BuildContext context) {
    final pages = {for (final h in highlights) h.page ?? 1}.toList()..sort();
    if (pages.isEmpty) {
      return Text(
        'No positions were recorded for this document. Open it to compare the values.',
        style: Theme.of(context).textTheme.bodySmall,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Page map — where each value was read (open the document to see the page itself).',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText)),
        const SizedBox(height: 6),
        for (final page in pages) ...[
          Text('Page $page', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 4),
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: AspectRatio(
                aspectRatio: 595 / 842,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: Colors.black26),
                    boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 4, offset: Offset(0, 2))],
                  ),
                  child: LayoutBuilder(
                    builder: (context, box) => Stack(
                      children: _regionLayer(box, highlights, selectedKey, onSelect, page: page),
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }
}
