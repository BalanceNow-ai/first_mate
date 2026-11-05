import 'dart:io';

import 'package:helm_marine/features/checklists/data/checklist_api.dart';
import 'package:path_provider/path_provider.dart';

/// Where an export will be shown (no placeholder needed off the web).
class ExportTarget {
  ExportTarget._();

  factory ExportTarget.open(ExportFormat format) => ExportTarget._();

  void cancel() {}
}

/// Saves [export] to the app's documents folder; returns a description with the path.
Future<String> deliverExport(ChecklistExport export, ExportTarget target) async {
  final dir = await getApplicationDocumentsDirectory();
  final file = File('${dir.path}${Platform.pathSeparator}${export.filename}');
  await file.writeAsString(export.content);
  return 'Saved to ${file.path}';
}
