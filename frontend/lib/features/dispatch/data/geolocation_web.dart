import 'dart:async';
import 'dart:js_interop';

import 'package:helm_marine/features/dispatch/data/geolocation.dart';

@JS('navigator.geolocation')
external _Geolocation? get _geolocation;

extension type _Geolocation._(JSObject _) implements JSObject {
  external void getCurrentPosition(JSFunction success, JSFunction error, _PositionOptions options);
}

extension type _PositionOptions._(JSObject _) implements JSObject {
  external factory _PositionOptions({bool enableHighAccuracy, int timeout, int maximumAge});
}

extension type _Position._(JSObject _) implements JSObject {
  external _Coordinates get coords;
  external JSNumber get timestamp;
}

extension type _Coordinates._(JSObject _) implements JSObject {
  external JSNumber get latitude;
  external JSNumber get longitude;
  external JSNumber? get accuracy;
  external JSNumber? get heading;
  external JSNumber? get speed;
}

extension type _PositionError._(JSObject _) implements JSObject {
  external int get code;
}

const bool geolocationSupported = true;

double? _finite(JSNumber? n) {
  if (n == null) return null;
  final v = n.toDartDouble;
  return v.isFinite ? v : null;
}

/// One fresh reading from `navigator.geolocation` (no cached positions).
Future<DeviceReading> readDevicePosition() {
  final geo = _geolocation;
  if (geo == null) {
    return Future.error(const GeolocationFailure('This browser does not provide a location service.'));
  }
  final done = Completer<DeviceReading>();
  void onSuccess(_Position p) {
    final c = p.coords;
    final speedMs = _finite(c.speed);
    final heading = _finite(c.heading);
    done.complete(DeviceReading(
      lat: c.latitude.toDartDouble,
      lng: c.longitude.toDartDouble,
      recordedAt: DateTime.fromMillisecondsSinceEpoch(p.timestamp.toDartDouble.round(), isUtc: true),
      accuracyM: _finite(c.accuracy),
      headingDeg: heading == null || heading < 0 || heading >= 360 ? null : heading,
      speedKnots: speedMs == null || speedMs < 0 ? null : speedMs * 1.9438444924,
    ));
  }

  void onError(_PositionError e) {
    done.completeError(GeolocationFailure(switch (e.code) {
      1 => 'Location permission was denied. Allow location access for this site to share your position.',
      2 => 'Your position is unavailable right now.',
      3 => 'Getting your position timed out. Try again.',
      _ => 'Your position could not be read.',
    }));
  }

  geo.getCurrentPosition(
    onSuccess.toJS,
    onError.toJS,
    _PositionOptions(enableHighAccuracy: true, timeout: 20000, maximumAge: 0),
  );
  return done.future;
}
