import 'package:helm_marine/features/dispatch/data/geolocation.dart';

/// Non-web builds have no geolocation plugin in this release.
const bool geolocationSupported = false;

Future<DeviceReading> readDevicePosition() => Future.error(
      const GeolocationFailure('Sharing your position is available in the web dispatch app in this build.'),
    );
