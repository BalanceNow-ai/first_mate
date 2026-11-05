import 'dart:js_interop';

import 'package:helm_marine/features/checklists/data/checklist_api.dart';
import 'package:web/web.dart' as web;

/// Where an export will be shown. Created synchronously in the tap handler so
/// the browser treats the new tab as user-initiated (not a blocked popup).
class ExportTarget {
  ExportTarget._(this._window);

  final web.Window? _window;

  /// Opens a placeholder tab for HTML; CSV needs none (it downloads).
  factory ExportTarget.open(ExportFormat format) {
    if (format != ExportFormat.html) return ExportTarget._(null);
    final win = web.window.open('', '_blank');
    win?.document.title = 'Preparing checklist…';
    return ExportTarget._(win);
  }

  /// Closes the placeholder tab (e.g. when the download failed).
  void cancel() => _window?.close();
}

/// Shows [export]; returns a short user-facing description of what happened.
Future<String> deliverExport(ChecklistExport export, ExportTarget target) async {
  final blob = web.Blob(
    [export.content.toJS].toJS,
    web.BlobPropertyBag(type: '${export.mimeType};charset=utf-8'),
  );
  final url = web.URL.createObjectURL(blob);
  final win = target._window;
  if (export.mimeType == ExportFormat.html.mimeType && win != null) {
    win.location.href = url;
    return 'Printable checklist opened in a new tab';
  }
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = export.filename
    ..style.display = 'none';
  if (export.mimeType == ExportFormat.html.mimeType) anchor.target = '_blank';
  web.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to start the download before releasing the blob.
  Future<void>.delayed(const Duration(minutes: 1), () => web.URL.revokeObjectURL(url));
  return 'Downloaded ${export.filename}';
}
