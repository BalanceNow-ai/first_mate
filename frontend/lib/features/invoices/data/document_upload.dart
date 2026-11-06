import 'dart:math';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:helm_marine/features/invoices/data/invoices_api.dart';

/// A file the user chose (bytes in memory; never a storage path).
class PickedDocument {
  const PickedDocument({required this.name, required this.bytes, this.contentType});

  final String name;
  final Uint8List bytes;
  final String? contentType;

  int get size => bytes.length;
}

const acceptedDocumentExtensions = ['pdf', 'jpg', 'jpeg', 'png', 'webp', 'heic'];

String? contentTypeFor(String name) {
  final dot = name.lastIndexOf('.');
  final ext = dot < 0 ? '' : name.substring(dot + 1).toLowerCase();
  return switch (ext) {
    'pdf' => 'application/pdf',
    'jpg' || 'jpeg' => 'image/jpeg',
    'png' => 'image/png',
    'webp' => 'image/webp',
    'heic' => 'image/heic',
    _ => null,
  };
}

/// Opens the platform file chooser (PDF or photo). Null when cancelled.
typedef DocumentPicker = Future<PickedDocument?> Function();

final documentPickerProvider = Provider<DocumentPicker>((ref) => () async {
      final file = await FilePicker.pickFile(
        dialogTitle: 'Choose the invoice (PDF or photo)',
        type: FileType.custom,
        allowedExtensions: acceptedDocumentExtensions,
      );
      if (file == null) return null;
      final bytes = await file.readAsBytes();
      return PickedDocument(name: file.name, bytes: bytes, contentType: contentTypeFor(file.name));
    });

/// How often (and how many times) upload/extraction status is polled.
final invoicePollIntervalProvider = Provider<Duration>((ref) => const Duration(seconds: 1));
final invoicePollAttemptsProvider = Provider<int>((ref) => 90);

enum UploadStage {
  starting('Starting the upload'),
  sending('Sending the file'),
  checking('Checking the file'),
  done('File ready');

  const UploadStage(this.label);

  final String label;
}

/// Thrown when the server rejects an uploaded file (unsafe or unsupported).
class UploadRejected implements Exception {
  const UploadRejected(this.reason);

  final String? reason;

  @override
  String toString() => rejectionText(reason);
}

/// Thrown when processing takes longer than we wait (the upload continues on
/// the server and can be resumed by checking the file again).
class UploadStillProcessing implements Exception {
  const UploadStillProcessing(this.assetId);

  final String assetId;

  @override
  String toString() => 'The file is still being checked. Try again in a moment.';
}

/// intent → PUT raw bytes → poll until `available` (or `rejected`).
Future<ServiceAsset> uploadDocument({
  required InvoicesApi api,
  required PickedDocument document,
  required Future<AssetIntent> Function() createIntent,
  required Duration pollInterval,
  required int pollAttempts,
  void Function(UploadStage stage)? onStage,
}) async {
  onStage?.call(UploadStage.starting);
  final intent = await createIntent();
  var asset = intent.asset;
  if (intent.uploadNeeded) {
    onStage?.call(UploadStage.sending);
    asset = await api.putContent(asset.id, document.bytes);
  }
  onStage?.call(UploadStage.checking);
  return waitForAsset(api: api, asset: asset, pollInterval: pollInterval, pollAttempts: pollAttempts, onStage: onStage);
}

Future<ServiceAsset> waitForAsset({
  required InvoicesApi api,
  required ServiceAsset asset,
  required Duration pollInterval,
  required int pollAttempts,
  void Function(UploadStage stage)? onStage,
}) async {
  var current = asset;
  for (var i = 0; !current.isFinished; i++) {
    if (i >= pollAttempts) throw UploadStillProcessing(current.id);
    await Future<void>.delayed(pollInterval);
    current = await api.asset(current.id);
  }
  if (!current.isAvailable) throw UploadRejected(current.rejectionReason);
  onStage?.call(UploadStage.done);
  return current;
}

final _random = Random.secure();

/// A unique idempotency key for one user action.
String newIdempotencyKey(String prefix) {
  final now = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
  final salt = '${_random.nextInt(0x7fffffff).toRadixString(36)}${_random.nextInt(0x7fffffff).toRadixString(36)}';
  return '$prefix-$now-$salt';
}
