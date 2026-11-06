import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/features/invoices/data/document_upload.dart';

void main() {
  test('idempotency keys match the server pattern and are unique', () {
    final pattern = RegExp(r'^[A-Za-z0-9_\-:.]{8,100}$');
    final keys = {for (var i = 0; i < 200; i++) newIdempotencyKey('invoice-upload')};
    expect(keys, hasLength(200));
    expect(keys.every(pattern.hasMatch), isTrue);
  });

  test('content types are declared for display only from the file name', () {
    expect(contentTypeFor('Invoice.PDF'), 'application/pdf');
    expect(contentTypeFor('photo.jpeg'), 'image/jpeg');
    expect(contentTypeFor('scan.png'), 'image/png');
    expect(contentTypeFor('notes.txt'), isNull);
  });
}
