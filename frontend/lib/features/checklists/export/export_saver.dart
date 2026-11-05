/// Delivers a checklist export to the user: on the web the printable HTML opens
/// in a new tab (fetched with the user's token and shown from a blob URL) and
/// CSV downloads; elsewhere the file is saved to the app's documents folder.
library;

export 'export_saver_io.dart' if (dart.library.js_interop) 'export_saver_web.dart';
