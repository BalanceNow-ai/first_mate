/// Hands a file the app fetched (with the user's token, as bytes) to the person:
/// on the web it downloads from a short-lived blob URL; elsewhere it is written to
/// a temporary file and opened with the platform's viewer. A token never goes
/// into a URL.
library;

import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'file_saver_io.dart' if (dart.library.js_interop) 'file_saver_web.dart' as impl;

/// A downloaded file held in memory.
class DownloadedFile {
  const DownloadedFile({required this.bytes, required this.filename, required this.contentType});

  final Uint8List bytes;
  final String filename;
  final String contentType;
}

/// Saves/opens [file]; returns a short description of what happened.
typedef FileSaver = Future<String> Function(DownloadedFile file);

final fileSaverProvider = Provider<FileSaver>((ref) => impl.saveFile);

/// The filename from a `Content-Disposition` header, else [fallback]. Only a
/// plain basename is kept (no paths).
String filenameFromDisposition(String? header, String fallback) {
  if (header == null) return fallback;
  final m = RegExp(r'filename\*?="?([^";]+)"?', caseSensitive: false).firstMatch(header);
  final raw = m?.group(1)?.trim();
  if (raw == null || raw.isEmpty) return fallback;
  final base = raw.split(RegExp(r'[/\\]')).last;
  return RegExp(r'^[A-Za-z0-9._ -]{1,120}$').hasMatch(base) ? base : fallback;
}
