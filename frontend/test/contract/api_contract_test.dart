// Contract tests: the Flutter models parse REAL server payloads captured from
// the local API by scripts/capture_api_fixtures.py (test/fixtures/api/*.json).
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/config/public_config.dart';
import 'package:helm_marine/core/models/cart.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/models/user.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/money/money.dart';

import '../helpers/fakes.dart';

void main() {
  group('identity', () {
    test('POST /auth/provision 201 parses as a created profile', () {
      final result = ProvisionResult.fromJson(fixtureMap('provision_created'));
      expect(result.created, isTrue);
      expect(result.user.role, 'customer');
      expect(result.user.fullName, 'Fixture Skipper');
      expect(result.user.phone, isNull);
      expect(result.user.email, endsWith('@example.test'));
      expect(result.user.createdAt.isUtc, isTrue);
    });

    test('POST /auth/provision 200 (idempotent repeat) is not "created"', () {
      final first = ProvisionResult.fromJson(fixtureMap('provision_created'));
      final again = ProvisionResult.fromJson(fixtureMap('provision_existing'));
      expect(again.created, isFalse);
      expect(again.user.id, first.user.id);
    });

    test('GET /auth/me parses as User with the same id', () {
      final me = User.fromJson(fixtureMap('auth_me'));
      final provisioned = User.fromJson(fixtureMap('provision_created'));
      expect(me.id, provisioned.id);
      expect(me.displayName, 'Fixture Skipper');
    });
  });

  group('vessels', () {
    test('POST /vessels/ response maps every canonical field', () {
      final v = Vessel.fromJson(fixtureMap('vessel_create'));
      expect(v.nickname, 'Sea Biscuit');
      expect(v.make, 'Haines Hunter');
      expect(v.model, 'SF600');
      expect(v.year, 2018);
      expect(v.hullType, 'fibreglass');
      expect(v.lengthFt, 19.5);
      expect(v.primaryUse, 'fishing');
      expect(v.propulsionType, 'outboard');
      expect(v.engineMake, 'Mercury');
      expect(v.engineModel, 'F150');
      expect(v.engineYear, 2018);
      expect(v.engineSerial, '1B123456');
      expect(v.engineHours, 420);
      expect(v.hin, 'NZ-HHB12345C818');
      expect(v.hinStatus, isNull);
      expect(v.hinDecoded, isNull);
      expect(v.isPrimary, isTrue, reason: 'first vessel becomes primary');
      expect(v.label, 'Sea Biscuit (2018 Haines Hunter SF600)');
    });

    test('a minimal vessel has null optional fields', () {
      final v = Vessel.fromJson(fixtureMap('vessel_create_minimal'));
      expect(v.nickname, 'Tender');
      expect(v.year, 2005);
      expect(v.lengthFt, isNull);
      expect(v.engineMake, isNull);
      expect(v.engineHours, isNull);
      expect(v.isPrimary, isFalse);
    });

    test('GET /vessels/ lists primary first', () {
      final list = [for (final j in fixture('vessels_list') as List) Vessel.fromJson((j as Map).cast())];
      expect(list, hasLength(2));
      expect(list.first.isPrimary, isTrue);
      expect(list.first.nickname, 'Sea Biscuit');
      expect(fixture('vessels_empty'), isEmpty);
    });

    test('VesselDraft sends only canonical writable fields', () {
      final response = fixtureMap('vessel_create');
      final draft = VesselDraft.fromVessel(Vessel.fromJson(response));
      final create = draft.toCreateJson();
      final update = draft.toUpdateJson();
      const readOnly = {'id', 'user_id', 'hin_status', 'hin_decoded', 'model_year_id', 'created_at', 'updated_at'};
      for (final body in [create, update]) {
        // Every key the client sends is a field the server returns (canonical name)…
        expect(response.keys, containsAll(body.keys));
        // …and none of them is server-owned or a legacy alias.
        expect(body.keys.toSet().intersection(readOnly), isEmpty);
        expect(body.containsKey('name'), isFalse);
        expect(body.containsKey('hull_material'), isFalse);
        expect(body.containsKey('engine_type'), isFalse);
      }
      expect(create['nickname'], 'Sea Biscuit');
      expect(create['year'], 2018);
      expect(create['length_ft'], 19.5);
      expect(create['engine_hours'], 420);
    });

    test('create omits empty optionals; update sends null to clear them', () {
      const draft = VesselDraft(nickname: 'Tender', make: 'Quintrex', model: '350 Dory', year: 2005);
      expect(draft.toCreateJson().keys, unorderedEquals(['nickname', 'make', 'model', 'year', 'is_primary']));
      expect(draft.toUpdateJson()['engine_make'], isNull);
      expect(draft.toUpdateJson().containsKey('engine_make'), isTrue);
    });
  });

  group('products', () {
    test('ProductResponse with verified fit (serialised by catalogue.product_response)', () {
      final p = Product.fromJson(fixtureMap('product_detail_fit'));
      expect(p.name, 'Water Pump Impeller Kit');
      expect(p.priceCents, 8990);
      expect(p.salePriceCents, 7490);
      expect(p.effectivePriceCents, 7490);
      expect(p.onSale, isTrue);
      expect(p.priceText, r'$74.90');
      expect(p.regularPriceText, r'$89.90');
      expect(p.stockQuantity, 12);
      expect(p.inStock, isTrue);
      expect(p.weightGrams, 180);
      expect(p.images, ['https://cdn.example.invalid/impeller.jpg']);
      expect(p.oemPartNumbers, ['47-43026Q06']);
      expect(p.partRole, 'impeller');
      expect(p.fitmentScope, 'specific');
      expect(p.dangerousGoods, isFalse);
      expect(p.specifications, {'vanes': 6});
      expect(p.fitment!.status, FitmentStatus.verifiedFit);
      expect(p.fitment!.status.fits, isTrue);
      expect(p.fitment!.message, 'Fits Sea Biscuit (2018 Haines Hunter SF600)');
      expect(p.fitment!.reasons, isNotEmpty);
    });

    test('a product without a vessel has no fitment', () {
      final p = Product.fromJson(fixtureMap('product_detail_no_vessel'));
      expect(p.fitment, isNull);
      expect(p.toString(), isNotEmpty);
    });

    test('product list envelope {items,total,offset,limit,vessel}', () {
      final page = ProductPage.fromJson(fixtureMap('products_list'));
      expect(page.total, 4);
      expect(page.offset, 0);
      expect(page.limit, 20);
      expect(page.hasMore, isFalse);
      expect(page.vessel!.label, 'Sea Biscuit (2018 Haines Hunter SF600)');
      final byName = {for (final p in page.items) p.name: p};
      expect(byName['Water Pump Impeller Kit']!.fitment!.status, FitmentStatus.verifiedFit);
      expect(byName['Fuel Filter Element']!.fitment!.status, FitmentStatus.verifiedMismatch);
      expect(byName['Fuel Filter Element']!.fitment!.status.fits, isFalse);
      final ties = byName['UV Stabilised Cable Ties (100)']!;
      expect(ties.fitment!.status, FitmentStatus.universal);
      expect(ties.inStock, isFalse);
      expect(ties.stockQuantity, 0);
      expect(ties.onSale, isFalse);
      expect(ties.salePriceCents, isNull);
      final flares = byName['Marine Distress Flares (pack of 3)']!;
      expect(flares.fitment!.status, FitmentStatus.unknown);
      expect(flares.fitment!.status.fits, isFalse, reason: 'unknown is never a fit');
      expect(flares.dangerousGoods, isTrue);
    });

    test('unrecognised fitment statuses are treated as unknown', () {
      expect(FitmentStatus.parse('probably_fits'), FitmentStatus.unknown);
      expect(FitmentStatus.parse(null), FitmentStatus.unknown);
    });
  });

  group('cart', () {
    test('GET /cart/ empty', () {
      final cart = Cart.fromJson(fixtureMap('cart_empty'));
      expect(cart.isEmpty, isTrue);
      expect(cart.subtotalCents, 0);
      expect(cart.currency, 'NZD');
      expect(cart.hasIssues, isFalse);
    });

    test('POST /cart/items returns the cart with server-priced lines', () {
      final cart = Cart.fromJson(fixtureMap('cart_with_item'));
      final product = Product.fromJson(fixtureMap('product_detail_fit'));
      expect(cart.items, hasLength(1));
      final line = cart.items.single;
      expect(line.quantity, 2);
      // The sale price shown on the product equals the cart unit price (J3).
      expect(line.unitPriceCents, product.effectivePriceCents);
      expect(line.lineTotalCents, 14980);
      expect(cart.subtotalCents, 14980);
      expect(cart.itemCount, 2);
      expect(line.product.name, product.name);
      expect(line.product.salePriceCents, 7490);
      expect(line.product.onSale, isTrue);
      expect(line.issues, isEmpty);
      expect(formatCents(cart.subtotalCents), r'$149.80');
    });

    test('per-line issues when stock drops below the cart quantity', () {
      final cart = Cart.fromJson(fixtureMap('cart_with_issues'));
      expect(cart.hasIssues, isTrue);
      final line = cart.items.single;
      expect(line.issues, ['insufficient_stock']);
      expect(line.product.stockQuantity, 1);
      expect(cartIssueText(line.issues.single, line.product), 'Only 1 in stock — reduce the quantity');
    });
  });

  group('public config', () {
    test('GET /api/v1/config/public', () {
      final c = PublicConfig.fromJson(fixtureMap('config_public'));
      expect(c.environment, 'development');
      expect(c.currency, 'NZD');
      expect(c.payments.provider, 'local');
      expect(c.payments.localTestMode, isTrue);
      expect(c.payments.stripePublishableKey, isNull);
      expect(c.payments.method('card')!.enabled, isTrue);
      final afterpay = c.payments.method('afterpay')!;
      expect(afterpay.enabled, isFalse);
      expect(afterpay.reason, contains('Afterpay is not offered'));
      expect(c.payments.method('laybuy')!.enabled, isFalse);
      expect(c.delivery.courier.enabled, isTrue);
      expect(c.delivery.helmDash.enabled, isFalse);
      expect(c.delivery.helmDash.reason, 'Helm Dash is not operating');
      expect(c.delivery.clickAndCollectLocation, contains('Westhaven'));
      expect(c.delivery.freeShippingThresholdCents, 15000);
      expect(c.delivery.dangerousGoodsDeliveryTypes, ['click_and_collect']);
      expect(c.ai.enabled, isFalse);
      expect(c.ai.localSubstitute, isFalse);
      expect(c.content.provider, 'disabled');
      expect(c.mapboxPublicToken, isNull);
      expect(c.warehouseLat, closeTo(-36.84, 0.01));
    });
  });

  group('errors {detail, code}', () {
    test('401 unauthenticated', () {
      final e = ApiError.fromResponse(401, fixture('error_unauthenticated'));
      expect(e.code, 'invalid_token');
      expect(e.detail, 'Authentication required');
      expect(e.isUnauthorized, isTrue);
    });

    test('403 profile_not_provisioned', () {
      final e = ApiError.fromResponse(403, fixture('error_profile_not_provisioned'));
      expect(e.isProfileNotProvisioned, isTrue);
      expect(e.detail, contains('profile has not been created'));
    });

    test('404 not_found', () {
      final e = ApiError.fromResponse(404, fixture('error_not_found'));
      expect(e.code, 'not_found');
      expect(e.detail, 'Vessel not found');
    });

    test('409 insufficient_stock keeps extra fields', () {
      final e = ApiError.fromResponse(409, fixture('error_insufficient_stock'));
      expect(e.code, 'insufficient_stock');
      expect(e.extra['available_quantity'], 12);
    });

    test('422 validation_error lists field errors', () {
      final e = ApiError.fromResponse(422, fixture('error_validation'));
      expect(e.code, 'validation_error');
      expect(e.errors.single.field, 'role');
      expect(e.errors.single.type, 'extra_forbidden');
      expect(describeError(e), contains('role'));
    });

    test('non-contract bodies never leak raw text', () {
      final e = ApiError.fromResponse(502, '<html>Bad gateway</html>');
      expect(e.detail, isNot(contains('<html>')));
      expect(e.code, 'http_error');
    });
  });
}
