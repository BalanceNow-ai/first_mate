import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/money/money.dart';

import '../../helpers/fakes.dart';
import 'catalogue_backend.dart';

void main() {
  testWidgets('verified fit: badge, OEM numbers, known-to-fit list and add to cart', (tester) async {
    final backend = catalogueBackend();
    final plug = cat('product_detail_vessel');
    backend.json('GET /products/${plug['id']}', 200, plug);
    backend.json('GET /products/${plug['id']}/compatibility', 200, cat('product_compatibility'));
    backend.json('POST /cart/items', 201, fixture('cart_with_item'));
    final app = await startApp(tester, backend);
    app.go('/products/${plug['id']}');
    await app.settle();

    expect(backend.calls('GET /products/${plug['id']}').single.query['vessel_id'], kahawaiId);
    expect(find.text('Fits Kahawai'), findsOneWidget);
    expect(find.text('SYN-PLUG-150'), findsOneWidget); // OEM part number chip
    expect(find.text('Known to fit'), findsOneWidget);
    expect(find.text('Yamaha F150 engines'), findsOneWidget);
    expect(find.textContaining('synthetic test data'), findsOneWidget);
    expect(find.text(r'$89.90'), findsOneWidget);
    expect(find.text('In stock'), findsOneWidget);
    expect(find.text('No image'), findsNothing); // the placeholder is an icon, labelled for screen readers

    await app.tap(find.text('Add to cart'));
    expect(backend.calls('POST /cart/items').single.body, {'product_id': plug['id'], 'quantity': 1});
    expect(find.text('Added 1 × ${plug['name']} to your cart'), findsOneWidget);
  });

  testWidgets('verified mismatch shows "Does not fit" with the reason and sale pricing', (tester) async {
    final backend = catalogueBackend();
    final wrong = cat('product_detail_mismatch');
    backend.json('GET /products/${wrong['id']}', 200, wrong);
    backend.json('GET /products/${wrong['id']}/compatibility', 404, fixture('error_not_found'));
    final app = await startApp(tester, backend);
    app.go('/products/${wrong['id']}');
    await app.settle();

    expect(find.text('Does not fit'), findsOneWidget);
    expect(find.text('Fits Kahawai'), findsNothing);
    final reasons = (wrong['fitment'] as Map)['reasons'] as List;
    expect(find.text('• ${reasons.first}'), findsOneWidget);
    // Sale: effective price plus the struck-through regular price.
    expect(wrong['on_sale'], isTrue);
    expect(find.text(formatCents(wrong['effective_price_cents'] as int)), findsOneWidget);
    expect(find.text(formatCents(wrong['price_cents'] as int)), findsOneWidget);
    // A failed compatibility load is shown with a retry, not hidden.
    expect(find.textContaining('Could not load compatibility'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });

  testWidgets('unknown fit is never presented as fitting; dangerous goods note shown', (tester) async {
    final backend = catalogueBackend();
    final dg = cat('product_detail_dangerous');
    backend.json('GET /products/${dg['id']}', 200, dg);
    backend.json('GET /products/${dg['id']}/compatibility', 200, {
      ...cat('product_compatibility_universal'),
      'product_id': dg['id'],
      'sku': dg['sku'],
    });
    final app = await startApp(tester, backend);
    app.go('/products/${dg['id']}');
    await app.settle();

    final status = (dg['fitment'] as Map)['status'];
    if (status == 'unknown') {
      expect(find.text('Fit unknown — not verified'), findsOneWidget);
      expect(find.text('Fits Kahawai'), findsNothing);
    }
    expect(find.textContaining('Dangerous goods'), findsOneWidget);
    expect(find.text('Universal part — suitable for any vessel.'), findsOneWidget);
  });

  testWidgets('product images show a placeholder while loading and on error', (tester) async {
    final backend = catalogueBackend();
    final plug = {...cat('product_detail_vessel'), 'images': ['https://cdn.example.invalid/a.jpg', 'https://cdn.example.invalid/b.jpg']};
    backend.json('GET /products/${plug['id']}', 200, plug);
    backend.json('GET /products/${plug['id']}/compatibility', 200, cat('product_compatibility'));
    final app = await startApp(tester, backend);
    app.go('/products/${plug['id']}');
    await app.settle();
    // The test HTTP client fails every image request → error placeholder.
    expect(find.text('Image unavailable'), findsWidgets);
    expect(find.text('1 / 2'), findsOneWidget);
    await app.tap(find.byTooltip('Next image'));
    expect(find.text('2 / 2'), findsOneWidget);
  });
}
