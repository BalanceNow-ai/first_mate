import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_client.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/equipment.dart';
import 'package:helm_marine/core/session/session.dart';
import 'package:helm_marine/features/products/data/api_call.dart';

/// Vessel-garage API scoped to the signed-in user.
final garageApiProvider = Provider<GarageApi>((ref) {
  ref.watch(currentUserIdProvider);
  return GarageApi(ref.watch(dioProvider));
});

/// Typed access to the boat database, HIN decoding, vessel equipment,
/// verification requests, service records and service reminders.
class GarageApi {
  GarageApi(this._dio);

  final Dio _dio;

  // --- Boat database (public) ------------------------------------------------

  /// `POST /boat-db/hin/decode` — a suggestion only; never overwrites user input.
  Future<HinDecode> decodeHin(String hin) => apiCall(
        () => _dio.post('/boat-db/hin/decode', data: {'hin': hin}),
        (d) => HinDecode.fromJson(asMap(d)),
      );

  Future<List<BoatManufacturer>> manufacturers({String? q}) => apiCall(
        () => _dio.get('/boat-db/manufacturers',
            queryParameters: {if (q != null && q.trim().isNotEmpty) 'q': q.trim()}),
        (d) => [for (final m in asList(d)) BoatManufacturer.fromJson(m)],
      );

  Future<List<BoatModel>> models(String manufacturerId) => apiCall(
        () => _dio.get('/boat-db/manufacturers/$manufacturerId/models'),
        (d) => [for (final m in asList(d)) BoatModel.fromJson(m)],
      );

  Future<List<BoatModelYear>> modelYears(String modelId) => apiCall(
        () => _dio.get('/boat-db/models/$modelId/years'),
        (d) => [for (final y in asList(d)) BoatModelYear.fromJson(y)],
      );

  Future<BoatModelYearDetail> modelYear(String modelYearId) => apiCall(
        () => _dio.get('/boat-db/model-years/$modelYearId'),
        (d) => BoatModelYearDetail.fromJson(asMap(d)),
      );

  Future<List<EquipmentCategory>> equipmentCategories() => apiCall(
        () => _dio.get('/boat-db/equipment-categories'),
        (d) => [for (final c in asList(d)) EquipmentCategory.fromJson(c)],
      );

  // --- Equipment --------------------------------------------------------------

  Future<EquipmentList> equipment(String vesselId, {bool includeRemoved = false}) => apiCall(
        () => _dio.get('/vessels/$vesselId/equipment',
            queryParameters: {if (includeRemoved) 'include_removed': true}),
        (d) => EquipmentList.fromJson(asMap(d)),
      );

  Future<EquipmentItem> addEquipment(String vesselId, EquipmentDraft draft) => apiCall(
        () => _dio.post('/vessels/$vesselId/equipment', data: draft.toCreateJson()),
        (d) => EquipmentItem.fromJson(asMap(d)),
      );

  Future<EquipmentItem> updateEquipment(String vesselId, String equipmentId, EquipmentDraft draft) => apiCall(
        () => _dio.patch('/vessels/$vesselId/equipment/$equipmentId', data: draft.toUpdateJson()),
        (d) => EquipmentItem.fromJson(asMap(d)),
      );

  Future<void> removeEquipment(String vesselId, String equipmentId) =>
      apiCall(() => _dio.delete('/vessels/$vesselId/equipment/$equipmentId'), (_) {});

  /// Copies factory OEM records into installed equipment (all, or [oemIds]).
  Future<ApplyOemResult> applyOem(String vesselId, {List<String>? oemIds}) => apiCall(
        () => _dio.post('/vessels/$vesselId/equipment/apply-oem',
            data: {'oem_equipment_ids': ?oemIds}),
        (d) => ApplyOemResult.fromJson(asMap(d)),
      );

  Future<VerificationRequest> requestVerification(String vesselId, {String? note, String? evidenceUrl}) =>
      apiCall(
        () => _dio.post('/vessels/$vesselId/equipment/verification-requests', data: {
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
          if (evidenceUrl != null && evidenceUrl.trim().isNotEmpty) 'evidence_url': evidenceUrl.trim(),
        }),
        (d) => VerificationRequest.fromJson(asMap(d)),
      );

  Future<List<VerificationRequest>> verificationRequests(String vesselId) => apiCall(
        () => _dio.get('/vessels/$vesselId/equipment/verification-requests'),
        (d) => [for (final r in asList(d)) VerificationRequest.fromJson(r)],
      );

  // --- Service records --------------------------------------------------------

  Future<List<ServiceRecord>> serviceRecords(String vesselId) => apiCall(
        () => _dio.get('/vessels/$vesselId/service-records'),
        (d) => [for (final r in asList(d)) ServiceRecord.fromJson(r)],
      );

  Future<ServiceRecord> addServiceRecord(String vesselId, ServiceRecordDraft draft) => apiCall(
        () => _dio.post('/vessels/$vesselId/service-records', data: draft.toCreateJson()),
        (d) => ServiceRecord.fromJson(asMap(d)),
      );

  Future<ServiceRecord> updateServiceRecord(String vesselId, String recordId, ServiceRecordDraft draft) =>
      apiCall(
        () => _dio.patch('/vessels/$vesselId/service-records/$recordId', data: draft.toUpdateJson()),
        (d) => ServiceRecord.fromJson(asMap(d)),
      );

  Future<void> deleteServiceRecord(String vesselId, String recordId) =>
      apiCall(() => _dio.delete('/vessels/$vesselId/service-records/$recordId'), (_) {});

  // --- Service reminders ------------------------------------------------------

  /// [status] is `active` (default), `completed`, `dismissed` or `all`.
  Future<List<ServiceReminder>> reminders(String vesselId, {String status = 'active'}) => apiCall(
        () => _dio.get('/vessels/$vesselId/service-reminders', queryParameters: {'status': status}),
        (d) => [for (final r in asList(d)) ServiceReminder.fromJson(r)],
      );

  Future<ServiceReminder> addReminder(String vesselId, ReminderDraft draft) => apiCall(
        () => _dio.post('/vessels/$vesselId/service-reminders', data: draft.toCreateJson()),
        (d) => ServiceReminder.fromJson(asMap(d)),
      );

  Future<ServiceReminder> updateReminder(String vesselId, String reminderId, Map<String, dynamic> body) =>
      apiCall(
        () => _dio.patch('/vessels/$vesselId/service-reminders/$reminderId', data: body),
        (d) => ServiceReminder.fromJson(asMap(d)),
      );

  Future<void> deleteReminder(String vesselId, String reminderId) =>
      apiCall(() => _dio.delete('/vessels/$vesselId/service-reminders/$reminderId'), (_) {});

  Future<ReminderCompletion> completeReminder(
    String vesselId,
    String reminderId, {
    DateTime? completedOn,
    int? engineHours,
    bool recordService = true,
    String? notes,
  }) =>
      apiCall(
        () => _dio.post('/vessels/$vesselId/service-reminders/$reminderId/complete', data: {
          if (completedOn != null) 'completed_on': dayString(completedOn),
          'engine_hours': ?engineHours,
          'record_service': recordService,
          if (notes != null && notes.trim().isNotEmpty) 'notes': notes.trim(),
        }),
        (d) => ReminderCompletion.fromJson(asMap(d)),
      );
}
