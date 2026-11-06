import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

/// A file the person chose (camera capture or file chooser).
class PickedMedia {
  const PickedMedia({required this.bytes, required this.name, this.mimeType});

  final Uint8List bytes;
  final String name;
  final String? mimeType;
}

/// Picks a photo or a document. On mobile web, `camera: true` opens a file input
/// with `capture` so the phone camera starts; otherwise the file chooser opens.
abstract class MediaPicker {
  Future<PickedMedia?> pick({required bool camera});

  /// A PDF document (job evidence such as a manual, a previous invoice or a service record).
  Future<PickedMedia?> pickDocument();
}

class ImagePickerMediaPicker implements MediaPicker {
  ImagePickerMediaPicker([ImagePicker? picker]) : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<PickedMedia?> pick({required bool camera}) async {
    // No resizing or re-encoding: the server decodes, checks quality and strips metadata.
    final file = await _picker.pickImage(source: camera ? ImageSource.camera : ImageSource.gallery);
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    final name = file.name.isEmpty ? 'photo' : file.name;
    return PickedMedia(bytes: bytes, name: name, mimeType: file.mimeType);
  }

  @override
  Future<PickedMedia?> pickDocument() async {
    // The server checks the content itself (type, pages, active content) and keeps only a
    // metadata-stripped copy; nothing is changed here.
    final file = await FilePicker.pickFile(
      dialogTitle: 'Choose a document (PDF)',
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
    );
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    return PickedMedia(bytes: bytes, name: file.name.isEmpty ? 'document.pdf' : file.name, mimeType: 'application/pdf');
  }
}

final mediaPickerProvider = Provider<MediaPicker>((ref) => ImagePickerMediaPicker());

/// Opens a short-lived signed download link in a new browser tab.
typedef UrlOpener = Future<void> Function(Uri uri);

final urlOpenerProvider = Provider<UrlOpener>((ref) => (uri) async {
      await launchUrl(uri, mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank');
    });
