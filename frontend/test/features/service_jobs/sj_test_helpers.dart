// Shared helpers for the service-jobs client tests. Fixtures are REAL server
// payloads captured from the local stack by
// scripts/capture_api_fixtures_service_jobs.py into
// test/fixtures/api/service_jobs/ (nothing hand-written).
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:helm_marine/app.dart';
import 'package:helm_marine/core/router.dart';
import 'package:helm_marine/features/service_jobs/data/media_picker.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../helpers/fakes.dart';

dynamic sj(String name) => fixture('service_jobs/$name');

Map<String, dynamic> sjMap(String name) => (sj(name) as Map).cast<String, dynamic>();

List<Map<String, dynamic>> sjList(String name) => [for (final e in sj(name) as List) (e as Map).cast<String, dynamic>()];

/// The captured main job's id (all owner-side fixtures belong to it).
String get jobId => sjMap('job_after_upload')['id'] as String;

/// A picker returning a synthetic PNG (never touches a camera).
class FakePicker implements MediaPicker {
  FakePicker({this.result});

  PickedMedia? result;
  final List<bool> calls = [];

  @override
  Future<PickedMedia?> pick({required bool camera}) async {
    calls.add(camera);
    return result ?? PickedMedia(bytes: Uint8List.fromList(List.generate(64, (i) => i)), name: 'photo.png', mimeType: 'image/png');
  }
}

/// Records URLs that would open in a new tab.
class FakeOpener {
  final List<Uri> opened = [];
  Future<void> call(Uri uri) async => opened.add(uri);
}

/// Every owner-side GET for the captured job, from fixtures.
FakeBackend ownerBackend({String job = 'job_after_upload'}) {
  final b = fixtureBackend();
  final p = '/service-jobs/$jobId';
  b.json('GET /service-jobs/', 200, sj('jobs_list'));
  b.json('GET $p', 200, sj(job));
  b.json('GET $p/evidence-requests/next', 200, sj('next_after_upload'));
  b.json('GET $p/evidence-requests', 200, sj('requests_list'));
  b.json('GET $p/assets', 200, sj('assets_list'));
  b.json('GET $p/analysis', 200, sj('analysis_status'));
  b.json('GET $p/observations', 200, sj('observations'));
  b.json('GET $p/measurements', 200, sj('measurements'));
  b.json('GET $p/preparation-items', 200, sj('preparation_items'));
  b.json('GET $p/access/general', 200, sj('access_general_get'));
  b.json('GET $p/access/restricted', 200, sj('access_restricted'));
  b.json('GET $p/assignments', 200, sj('assignments'));
  b.json('GET $p/briefs', 200, sj('briefs'));
  b.json('GET $p/scopes', 200, sj('scopes'));
  b.json('GET $p/visits', 200, sj('visits'));
  b.json('GET $p/feedback', 200, sj('feedback_owner_open'));
  b.json('GET /contractors/me', 200, sj('contractor_me_empty'));
  b.json('GET /contractors/directory', 200, sj('directory'));
  return b;
}

/// The assigned contractor's view of the same job.
FakeBackend contractorBackend() {
  final b = fixtureBackend();
  final p = '/service-jobs/$jobId';
  final briefs = sjList('briefs_contractor');
  b.json('GET $p', 200, sj('job_contractor_view'));
  b.json('GET $p/briefs', 200, briefs);
  b.json('GET $p/briefs/${briefs.last['id']}', 200, sj('brief_contractor'));
  b.json('GET $p/evidence-requests', 200, sj('requests_contractor'));
  b.json('GET $p/assets', 200, sj('assets_contractor'));
  b.json('GET $p/observations', 200, sj('observations'));
  b.json('GET $p/measurements', 200, sj('measurements_contractor'));
  b.json('GET $p/preparation-items', 200, sj('preparation_items_contractor'));
  b.json('GET $p/access/general', 200, sj('access_general_get'));
  b.json('GET $p/access/restricted', 200, sj('access_restricted_contractor'));
  b.json('GET $p/scopes', 200, sj('scopes'));
  b.json('GET $p/visits', 200, sj('visits'));
  b.json('GET $p/feedback', 200, sj('feedback_contractor_blind'));
  b.json('GET /contractors/me', 200, sj('contractor_me'));
  b.json('GET /contractors/me/jobs', 200, sj('contractor_inbox_assigned'));
  return b;
}

/// The real app (router, shell) with a fake picker/opener, signed in.
class SjApp {
  SjApp(this.tester, this.backend, {FakePicker? picker})
      : picker = picker ?? FakePicker(),
        opener = FakeOpener();

  final WidgetTester tester;
  final FakeBackend backend;
  final FakePicker picker;
  final FakeOpener opener;
  late final ProviderContainer container;

  Future<void> start(String location, {Size size = const Size(1200, 2600)}) async {
    final gateway = fixtureGateway();
    final List<Override> overrides = [
      ...testOverrides(gateway: gateway, backend: backend),
      mediaPickerProvider.overrideWithValue(picker),
      urlOpenerProvider.overrideWithValue(opener.call),
      uploadPollIntervalProvider.overrideWithValue(Duration.zero),
    ];
    container = ProviderContainer(overrides: overrides, retry: (_, _) => null);
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const HelmApp()));
    await settle();
    go(location);
    await settle();
  }

  void go(String location) => container.read(routerProvider).go(location);

  String get location => container.read(routerProvider).routerDelegate.currentConfiguration.uri.toString();

  Future<void> settle() async {
    for (var i = 0; i < 25; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
      await tester.pump(const Duration(milliseconds: 50));
    }
    await tester.pumpAndSettle();
  }

  Future<void> tap(Finder finder) async {
    await tester.ensureVisible(finder.first);
    await tester.tap(finder.first);
    await settle();
  }

  Future<void> tapText(String text) => tap(find.text(text));

  Future<void> enter(String label, String text) async {
    final f = find.widgetWithText(TextFormField, label).evaluate().isNotEmpty
        ? find.widgetWithText(TextFormField, label)
        : find.widgetWithText(TextField, label);
    await tester.enterText(f.first, text);
    await tester.pump();
  }
}

/// A button/text inside the open dialog (not the page behind it).
Finder inDialog(String text) => find.descendant(of: find.byType(AlertDialog), matching: find.text(text));
