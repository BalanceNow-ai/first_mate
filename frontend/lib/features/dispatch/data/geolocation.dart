import 'package:helm_marine/features/dispatch/data/geolocation_stub.dart'
    if (dart.library.js_interop) 'package:helm_marine/features/dispatch/data/geolocation_web.dart' as impl;

/// One reading from the device's geolocation API.
class DeviceReading {
  const DeviceReading({
    required this.lat,
    required this.lng,
    required this.recordedAt,
    this.accuracyM,
    this.headingDeg,
    this.speedKnots,
  });

  final double lat;
  final double lng;
  final DateTime recordedAt;
  final double? accuracyM;
  final double? headingDeg;
  final double? speedKnots;
}

/// Why no reading was obtained.
class GeolocationFailure implements Exception {
  const GeolocationFailure(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Whether this build can read the device position.
bool get geolocationSupported => impl.geolocationSupported;

/// Asks the device for its current position (the browser prompts for
/// permission the first time). Only call this from an explicit user action.
Future<DeviceReading> readDevicePosition() => impl.readDevicePosition();
