import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/helm_map.dart';
import 'package:latlong2/latlong.dart';

/// Default view: the Hauraki Gulf.
const haurakiGulf = LatLng(-36.75, 175.0);

const _distance = Distance();

/// Nautical miles between two points (great-circle).
double nauticalMilesBetween(LatLng a, LatLng b) => _distance.as(LengthUnit.Meter, a, b) / 1852;

/// The enabled area containing [point], if any.
OperatingAreaSummary? areaContaining(List<OperatingAreaSummary> areas, LatLng point) {
  for (final a in areas) {
    if (nauticalMilesBetween(LatLng(a.centerLat, a.centerLng), point) <= a.radiusNm) return a;
  }
  return null;
}

/// A labelled point drawn on a [SeaMap].
class SeaMarker {
  const SeaMarker({required this.point, required this.label, required this.icon, required this.color});

  final LatLng point;
  final String label;
  final IconData icon;
  final Color color;
}

/// flutter_map with the configured tiles (Mapbox public token from
/// `/config/public`, else the build's tile template) and operating-area
/// circles. Without configured tiles it still draws the areas and markers on
/// a plain sea background and says that no base map is configured.
class SeaMap extends ConsumerWidget {
  const SeaMap({
    super.key,
    required this.center,
    this.zoom = 10,
    this.areas = const [],
    this.markers = const [],
    this.mapController,
    this.onTap,
    this.markerBuilder,
    this.semanticLabel,
  });

  final LatLng center;
  final double zoom;
  final List<OperatingAreaSummary> areas;
  final List<SeaMarker> markers;
  final MapController? mapController;
  final void Function(LatLng point)? onTap;

  /// Custom widget for a marker (e.g. a draggable pin).
  final Widget Function(SeaMarker marker)? markerBuilder;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tiles = ref.watch(mapTilesProvider);
    return Semantics(
      label: semanticLabel ?? 'Map showing ${markers.map((m) => m.label).join(', ')}',
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Stack(
          children: [
            Positioned.fill(
              child: FlutterMap(
                mapController: mapController,
                options: MapOptions(
                  initialCenter: center,
                  initialZoom: zoom,
                  backgroundColor: const Color(0xFFCFE3F0),
                  onTap: onTap == null ? null : (_, p) => onTap!(p),
                ),
                children: [
                  if (tiles != null)
                    TileLayer(
                      urlTemplate: tiles.urlTemplate,
                      additionalOptions: tiles.options,
                      userAgentPackageName: 'nz.co.helmmarine.helm_marine',
                    ),
                  CircleLayer(circles: [
                    for (final a in areas)
                      CircleMarker(
                        point: LatLng(a.centerLat, a.centerLng),
                        radius: a.radiusMetres,
                        useRadiusInMeter: true,
                        color: HelmTheme.seafoam.withValues(alpha: 0.15),
                        borderColor: HelmTheme.secondary,
                        borderStrokeWidth: 2,
                      ),
                  ]),
                  MarkerLayer(markers: [
                    for (final m in markers)
                      Marker(
                        point: m.point,
                        width: 48,
                        height: 48,
                        alignment: Alignment.topCenter,
                        child: markerBuilder?.call(m) ??
                            Tooltip(message: m.label, child: Icon(m.icon, color: m.color, size: 36)),
                      ),
                  ]),
                  if (tiles != null) RichAttributionWidget(attributions: [TextSourceAttribution(tiles.attribution)]),
                ],
              ),
            ),
            if (tiles == null)
              Positioned(
                left: 8,
                bottom: 8,
                right: 8,
                child: IgnorePointer(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.85),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Text(
                      'No base map tiles are configured for this build — areas and pins are drawn without a chart.',
                      style: TextStyle(fontSize: 12, color: HelmTheme.mutedText),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
