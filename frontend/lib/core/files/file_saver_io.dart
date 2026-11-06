import 'dart:io';

import 'package:helm_marine/core/files/file_saver.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

/// Writes [file] to a private temporary folder and opens it with the platform viewer.
Future<String> saveFile(DownloadedFile file) async {
  final dir = await getTemporaryDirectory();
  final out = File('${dir.path}${Platform.pathSeparator}${file.filename}');
  await out.writeAsBytes(file.bytes, flush: true);
  final opened = await launchUrl(Uri.file(out.path));
  return opened ? 'Opened ${file.filename}' : 'Saved ${file.filename} to ${out.path}';
}
