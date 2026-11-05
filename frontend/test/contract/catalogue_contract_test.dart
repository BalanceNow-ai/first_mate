// Contract tests for the catalogue, vessel garage, checklist and notification
// preference models. Every fixture is a REAL response captured from the local
// stack by scripts/capture_api_fixtures_pass2_catalogue.py
// (test/fixtures/api/catalogue/*).
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/catalogue.dart';
import 'package:helm_marine/core/models/checklist.dart';
import 'package:helm_marine/core/models/equipment.dart';
import 'package:helm_marine/core/models/notification_preferences.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/models/vessel.dart';

import '../helpers/fakes.dart';

Map<String, dynamic> cat(String name) => fixtureMap('catalogue/$name');
List<Map<String, dynamic>> catList(String name) =>
    [for (final e in fixture('catalogue/$name') as List) (e as Map).cast<String, dynamic>()];

void main() {
  group('products', () {
    test('GET /products/ without a vessel has no fitment and no vessel', () {
      final page = ProductPage.fromJson(cat('products_page'));
      expect(page.items, isNotEmpty);
      expect(page.vessel, isNull);
      expect(page.items.every((p) => p.fitment == null), isTrue);
      expect(page.offset, 0);
      expect(page.limit, 6);
      expect(page.total, greaterThan(page.items.length));
      expect(page.hasMore, isTrue);
    });

    test('GET /products/?vessel_id evaluates every item; unknown never fits', () {
      final page = ProductPage.fromJson(cat('products_page_vessel'));
      final vessel = Vessel.fromJson(cat('vessel_linked'));
      expect(page.vessel!.id, vessel.id);
      expect(page.vessel!.label, vessel.label);
      final statuses = {for (final p in page.items) p.fitment!.status};
      expect(statuses, containsAll(FitmentStatus.values));
      for (final p in page.items) {
        expect(p.fitment!.status.fits,
            p.fitment!.status == FitmentStatus.verifiedFit || p.fitment!.status == FitmentStatus.universal);
      }
      final plug = page.items.firstWhere((p) => p.sku == 'SYN-PLUG-150');
      expect(plug.fitment!.status, FitmentStatus.verifiedFit);
      expect(plug.partRole, 'spark_plug');
      final wrong = page.items.firstWhere((p) => p.sku == 'SYN-PLUG-140');
      expect(wrong.fitment!.status, FitmentStatus.verifiedMismatch);
      expect(wrong.onSale, isTrue);
      expect(wrong.effectivePriceCents, lessThan(wrong.priceCents));
    });

    test('compatible_only returns only verified fits and universal parts', () {
      final page = ProductPage.fromJson(cat('products_compatible'));
      expect(page.items, isNotEmpty);
      expect(page.items.every((p) => p.fitment!.status.fits), isTrue);
      expect(page.items.map((p) => p.sku), contains('SYN-PLUG-150'));
    });

    test('filtered and paged lists parse', () {
      final filtered = ProductPage.fromJson(cat('products_filtered'));
      expect(filtered.items.every((p) => p.partRole == 'spark_plug' && p.inStock), isTrue);
      final prices = [for (final p in filtered.items) p.effectivePriceCents];
      expect(prices, [...prices]..sort());
      final page2 = ProductPage.fromJson(cat('products_page2'));
      expect(page2.offset, 5);
      expect(page2.limit, 5);
    });

    test('categories and brands', () {
      final cats = [for (final c in catList('product_categories')) CategoryCount.fromJson(c)];
      expect(cats, isNotEmpty);
      final engine = cats.firstWhere((c) => c.category == 'Engine Parts');
      expect(engine.subCategories.map((s) => s.name), contains('Ignition'));
      expect(engine.count, engine.subCategories.fold<int>(0, (a, s) => a + s.count));
      final brands = [for (final b in catList('product_brands')) BrandCount.fromJson(b)];
      expect(brands.map((b) => b.brand), contains('FixtureParts'));
    });

    test('GET /search/products reports engine, notice and facets', () {
      final page = SearchPage.fromJson(cat('search_products'));
      expect(SearchEngine.values.map((e) => e.wire), contains(cat('search_products')['engine']));
      expect(page.items, isNotEmpty);
      expect(page.items.every((p) => p.fitment != null), isTrue);
      expect(page.facets.keys, containsAll(['category', 'brand', 'part_role']));
      expect(page.fellBack, page.engine == SearchEngine.postgresFallback);
    });

    test('product detail with a vessel, mismatch and dangerous goods', () {
      final plug = Product.fromJson(cat('product_detail_vessel'));
      expect(plug.fitment!.status, FitmentStatus.verifiedFit);
      expect(plug.oemPartNumbers, ['SYN-PLUG-150']);
      final wrong = Product.fromJson(cat('product_detail_mismatch'));
      expect(wrong.fitment!.status, FitmentStatus.verifiedMismatch);
      expect(wrong.fitment!.reasons, isNotEmpty);
      final dg = Product.fromJson(cat('product_detail_dangerous'));
      expect(dg.dangerousGoods, isTrue);
    });

    test('GET /products/{id}/compatibility is the verified "known to fit" list', () {
      final c = ProductCompatibility.fromJson(cat('product_compatibility'));
      expect(c.universal, isFalse);
      expect(c.knownToFit, hasLength(1));
      final k = c.knownToFit.single;
      expect(k.engineMake, 'Yamaha');
      expect(k.engineModel, 'F150');
      expect(k.isSynthetic, isTrue);
      expect(k.description, 'Yamaha F150 engines');
      final u = ProductCompatibility.fromJson(cat('product_compatibility_universal'));
      expect(u.universal, isTrue);
      expect(u.knownToFit, isEmpty);
    });

    test('compatible_only without a vessel is a 422 vessel_required', () {
      final e = ApiError.fromResponse(422, cat('error_vessel_required'));
      expect(e.code, 'vessel_required');
      expect(e.detail, 'compatible_only requires vessel_id');
    });
  });

  group('boat database & HIN', () {
    test('a recorded MIC identifies the manufacturer; the year is a suggestion', () {
      final d = HinDecode.fromJson(cat('hin_decode_valid'));
      expect(d.valid, isTrue);
      expect(d.status, 'valid');
      expect(d.normalized, 'NZ-Z9X12345C121');
      expect(d.input, 'nz-z9x12345c121');
      expect(d.modelYear, 2021);
      expect(d.manufacturer!.isSynthetic, isTrue);
      expect(d.warnings, isNotEmpty);
    });

    test('an unknown MIC decodes without a manufacturer', () {
      final d = HinDecode.fromJson(cat('hin_decode_unrecognised_mic'));
      expect(d.valid, isTrue);
      expect(d.manufacturer, isNull);
      expect(d.mic, 'SYN');
      expect(d.warnings.single, contains('not in the Helm boat database'));
    });

    test('an invalid HIN has no decode and a warning', () {
      final d = HinDecode.fromJson(cat('hin_decode_invalid'));
      expect(d.isInvalid, isTrue);
      expect(d.normalized, isNull);
      expect(d.modelYear, isNull);
      expect(d.confidence, 0);
    });

    test('manufacturers, models, years, lookup and categories', () {
      final makers = [for (final m in catList('boat_manufacturers_search')) BoatManufacturer.fromJson(m)];
      final maker = makers.firstWhere((m) => m.isSynthetic);
      expect(maker.micCodes, ['Z9X']);
      final models = [for (final m in catList('boat_models')) BoatModel.fromJson(m)];
      expect(models.every((m) => m.manufacturerId == maker.id), isTrue);
      final runabout = models.firstWhere((m) => m.name == 'Fixture 600 Runabout');
      expect(runabout.years, [2021, 2022, 2023]);
      final years = [for (final y in catList('boat_model_years')) BoatModelYear.fromJson(y)];
      expect(years.map((y) => y.year), [2021, 2022, 2023]);
      final lookup = BoatModelYearDetail.fromJson(cat('boat_lookup'));
      expect(lookup.year, 2021);
      expect(lookup.isSynthetic, isTrue);
      expect(lookup.equipment, isNotEmpty);
      expect(lookup.equipment.every((e) => !e.reliable), isTrue, reason: 'synthetic OEM data is low confidence');
      final detail = BoatModelYearDetail.fromJson(cat('boat_model_year_detail'));
      expect(detail.label, 'Synthetic Test Marine (fixture) Fixture 600 Runabout 2021');
      final cats = [for (final c in catList('equipment_categories')) EquipmentCategory.fromJson(c)];
      expect(cats.map((c) => c.slug), containsAll(['chartplotter', 'engine', 'vhf_radio']));
    });

    test('a vessel stores the decode as a suggestion and links its model year', () {
      final v = Vessel.fromJson(cat('vessel_linked'));
      expect(v.hinStatus, 'valid');
      expect(v.modelYearId, BoatModelYearDetail.fromJson(cat('boat_model_year_detail')).id);
      final stored = HinDecode.fromJson(v.hinDecoded!);
      expect(stored.note, contains('does not change the details you entered'));
      final unlinked = Vessel.fromJson(cat('vessel_unlinked'));
      expect(unlinked.modelYearId, isNull);
      expect(unlinked.make, 'Homebuilt', reason: 'owner input is never overwritten');
    });
  });

  group('equipment', () {
    test('factory OEM records are listed until applied, with low-confidence notes', () {
      final list = EquipmentList.fromJson(cat('equipment_list_factory'));
      expect(list.modelYearId, isNotNull);
      expect(list.installed, isEmpty);
      expect(list.factory, isNotEmpty);
      final f = list.factory.first;
      expect(f.provenance, 'oem_database');
      expect(f.reliability, Reliability.unconfirmed);
      expect(f.isSynthetic, isTrue);
      expect(f.displayNote, contains('not confirmed'));
    });

    test('owner equipment is owner-declared', () {
      final e = EquipmentItem.fromJson(cat('equipment_added'));
      expect(e.isInstalled, isTrue);
      expect(e.origin, 'user_added');
      expect(e.reliability, Reliability.ownerDeclared);
      expect(e.installedOn, DateTime(2022, 10, 1));
      final updated = EquipmentItem.fromJson(cat('equipment_updated'));
      expect(updated.model, 'echoMAP UHD 95sv');
      expect(updated.notes, isNull);
    });

    test('apply-oem copies factory records; removed rows are flagged', () {
      final applied = ApplyOemResult.fromJson(cat('equipment_apply_oem'));
      expect(applied.created, isNotEmpty);
      expect(applied.created.every((e) => e.origin == 'oem' && e.isInstalled), isTrue);
      final after = EquipmentList.fromJson(cat('equipment_list_applied'));
      expect(after.factory, isEmpty);
      final withRemoved = EquipmentList.fromJson(cat('equipment_list_with_removed'));
      expect(withRemoved.removed, hasLength(1));
      expect(withRemoved.installed.any((e) => e.isPendingReview), isTrue);
    });

    test('verification requests', () {
      final r = VerificationRequest.fromJson(cat('verification_request'));
      expect(r.isPending, isTrue);
      expect(r.equipmentIds, isNotEmpty);
      final list = [for (final x in catList('verification_requests')) VerificationRequest.fromJson(x)];
      expect(list.single.id, r.id);
      final e = ApiError.fromResponse(409, cat('error_verification_pending'));
      expect(e.code, 'verification_pending');
    });

    test('drafts use the canonical request names', () {
      final draft = EquipmentDraft(category: 'chartplotter', make: 'Garmin', installedOn: DateTime(2022, 10, 1));
      expect(draft.toCreateJson(), {'category': 'chartplotter', 'make': 'Garmin', 'installed_on': '2022-10-01'});
      expect(draft.toUpdateJson().keys,
          unorderedEquals(['category', 'make', 'model', 'serial_number', 'year', 'installed_on', 'notes']));
    });
  });

  group('service history', () {
    test('records carry integer cents', () {
      final r = ServiceRecord.fromJson(cat('service_record_created'));
      expect(r.costCents, 45000);
      expect(r.costText, r'$450.00');
      expect(r.performedOn, DateTime(2026, 9, 14));
      expect(ServiceRecord.fromJson(cat('service_record_updated')).costText, r'$465.00');
      expect([for (final x in catList('service_records')) ServiceRecord.fromJson(x)], hasLength(1));
    });

    test('reminders and completion create the next one', () {
      final r = ServiceReminder.fromJson(cat('reminder_created'));
      expect(r.isActive, isTrue);
      expect(r.dueText, 'Due 1 Oct 2026 or at 200 engine hours');
      expect(r.intervalText, 'Repeats every 12 months or every 100 hours');
      final done = ReminderCompletion.fromJson(cat('reminder_completed'));
      expect(done.completed.status, 'completed');
      expect(done.next!.dueEngineHours, 230);
      expect(done.serviceRecord!.engineHours, 130);
      final all = [for (final x in catList('reminders_all')) ServiceReminder.fromJson(x)];
      expect(all.map((x) => x.status), containsAll(['completed', 'active']));
      final e = ApiError.fromResponse(422, cat('error_reminder_needs_due'));
      expect(e.code, 'validation_error');
    });
  });

  group('checklists', () {
    test('before generation the set is empty but carries the disclaimer', () {
      final s = ChecklistSet.fromJson(cat('checklists_not_generated'));
      expect(s.generated, isFalse);
      expect(s.tiers, isEmpty);
      expect(s.disclaimer, contains('NOT a certified'));
      expect(ApiError.fromResponse(404, cat('error_checklists_not_generated')).code, 'checklists_not_generated');
    });

    test('generated tiers are cumulative and mark inherited items', () {
      final s = ChecklistSet.fromJson(cat('checklists_generated'));
      expect(s.tiers.map((t) => t.tier), ChecklistTierId.values);
      final day = s.tier(ChecklistTierId.grabAndGo)!;
      final offshore = s.tier(ChecklistTierId.offshorePassage)!;
      expect(day.items.every((i) => i.introducedIn == ChecklistTierId.grabAndGo), isTrue);
      expect(offshore.items.map((i) => i.id), containsAll(day.items.map((i) => i.id)));
      expect(offshore.total, offshore.items.length);
      expect(offshore.uncheckedLinked, offshore.items.where((i) => !i.isChecked && i.product != null).length);
      final unlinked = day.items.firstWhere((i) => i.linkStatus == LinkStatus.unlinked);
      expect(unlinked.product, isNull);
      expect(unlinked.searchHint!.partRole, unlinked.partRole);
      final linked = day.items.firstWhere((i) => i.linkStatus == LinkStatus.verifiedFit);
      expect(linked.fitment!.status, FitmentStatus.verifiedFit);
      expect(linked.searchHint, isNull);
      expect(ApiError.fromResponse(409, cat('error_checklists_exist')).code, 'checklists_exist');
    });

    test('ticking and linking return the item', () {
      final checked = ChecklistItem.fromJson(cat('checklist_item_checked'));
      expect(checked.isChecked, isTrue);
      expect(checked.checkedAt, isNotNull);
      final toggled = ChecklistItem.fromJson(cat('checklist_item_toggled'));
      expect(toggled.isChecked, isFalse);
      final unverified = ChecklistItem.fromJson(cat('checklist_item_linked_unverified'));
      expect(unverified.linkStatus, LinkStatus.userLinkedUnverified);
      expect(unverified.fitment!.status, FitmentStatus.unknown);
      expect(unverified.warning, contains('has not been verified'));
      final linked = ChecklistItem.fromJson(cat('checklist_item_linked'));
      expect(linked.linkStatus, LinkStatus.verifiedFit);
      expect(linked.warning, isNull);
      final mismatch = ApiError.fromResponse(409, cat('error_link_mismatch'));
      expect(mismatch.code, 'fitment_mismatch');
      expect(mismatch.detail, startsWith('Does not fit'));
      expect((mismatch.extra['fitment'] as Map)['status'], 'verified_mismatch');
    });

    test('add missing is idempotent: the second call adds nothing', () {
      final first = AddMissingResult.fromJson(cat('checklist_add_missing_first'));
      expect(first.tier, ChecklistTierId.grabAndGo);
      expect(first.addedCount, greaterThan(0));
      expect(first.lines.every((l) => l.status == 'added' && l.added == l.requested), isTrue);
      expect(first.skipped, isNotEmpty);
      final second = AddMissingResult.fromJson(cat('checklist_add_missing_second'));
      expect(second.addedCount, 0);
      expect(second.lines.every((l) => l.status == 'already_satisfied' && l.added == 0), isTrue);
      expect(second.lines.first.statusLabel, 'Already in cart');
    });

    test('tier endpoint and regenerate parse; exports carry the disclaimer', () {
      final tier = ChecklistTier.fromJson(cat('checklist_tier_offshore'));
      expect(tier.tier, ChecklistTierId.offshorePassage);
      final regen = ChecklistSet.fromJson(cat('checklists_regenerated'));
      expect(regen.generated, isTrue);
      final html = File('test/fixtures/api/catalogue/checklist_export.html').readAsStringSync();
      final csv = File('test/fixtures/api/catalogue/checklist_export.csv').readAsStringSync();
      expect(html, contains('NOT a certified'));
      expect(csv.split('\n')[1], contains('NOT a certified'));
    });

    test('local tick updates every tier and recomputes counts', () {
      final s = ChecklistSet.fromJson(cat('checklists_generated'));
      final item = s.tier(ChecklistTierId.grabAndGo)!.items.firstWhere((i) => i.product != null);
      final next = s.updateItem(item.id, (i) => i.copyWith(isChecked: true));
      for (final t in next.tiers) {
        expect(t.items.firstWhere((i) => i.id == item.id).isChecked, isTrue);
        expect(t.checked, 1);
      }
      expect(next.tier(ChecklistTierId.grabAndGo)!.uncheckedLinked,
          s.tier(ChecklistTierId.grabAndGo)!.uncheckedLinked - 1);
    });
  });

  group('notification preferences', () {
    test('GET and PUT parse with the transactional note', () {
      final p = NotificationPreferences.fromJson(cat('notification_preferences'));
      expect(p.marketing, isFalse);
      expect(p.transactionalNote, contains('always sent by email'));
      final u = NotificationPreferences.fromJson(cat('notification_preferences_updated'));
      expect(u.marketing, isTrue);
      expect(u.pushEnabled, isFalse);
      expect(NotificationPreferences.fields.map(p.value), everyElement(isA<bool>()));
      final e = ApiError.fromResponse(422, cat('error_preferences_unknown_field'));
      expect(e.errors.single.field, 'transactional');
    });
  });
}
