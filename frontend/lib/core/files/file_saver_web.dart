import 'dart:js_interop';

import 'package:helm_marine/core/files/file_saver.dart';
import 'package:web/web.dart' as web;

/// Downloads [file] from a blob URL (download attribute), then releases the URL.
Future<String> saveFile(DownloadedFile file) async {
  final blob = web.Blob([file.bytes.toJS].toJS, web.BlobPropertyBag(type: file.contentType));
  final url = web.URL.createObjectURL(blob);
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = file.filename
    ..rel = 'noopener'
    ..style.display = 'none';
  web.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to start the download before releasing the blob.
  Future<void>.delayed(const Duration(seconds: 30), () => web.URL.revokeObjectURL(url));
  return 'Downloaded ${file.filename}';
}
