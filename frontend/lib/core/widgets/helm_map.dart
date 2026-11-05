import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/config/app_config.dart';
import 'package:helm_marine/core/config/public_config.dart';
import 'package:helm_marine/core/config/public_config_provider.dart';
import 'package:latlong2/latlong.dart';

/// Raster tile source for [HelmMap].
class MapTiles {
  const MapTiles({required this.urlTemplate, required this.attribution, this.options = const {}});

  final String urlTemplate;
  final String attribution;

  /// Template placeholders such as `{accessToken}`.
  final Map<String, String> options;
}

const mapboxTileTemplate =
    'https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/tiles/256/{z}/{x}/{y}@2x'
    '?access_token={accessToken}';

/// Tiles to use: Mapbox raster tiles when the server publishes a Mapbox public
/// token, else the build's `MAP_TILE_URL_TEMPLATE`, else none (no map is drawn).
MapTiles? resolveMapTiles(AppConfig config, PublicConfig? publicConfig) {
  final token = publicConfig?.mapboxPublicToken;
  if (token != null && token.isNotEmpty) {
    return MapTiles(
      urlTemplate: mapboxTileTemplate,
      attribution: '© Mapbox © OpenStreetMap contributors',
      options: {'accessToken': token},
    );
  }
  if (config.mapTileUrlTemplate.isNotEmpty) {
    return MapTiles(
      urlTemplate: config.mapTileUrlTemplate,
      attribution: config.mapTileAttribution.isEmpty
          ? '© OpenStreetMap contributors'
          : config.mapTileAttribution,
    );
  }
  return null;
}

final mapTilesProvider = Provider<MapTiles?>((ref) {
  return resolveMapTiles(ref.watch(appConfigProvider), ref.watch(publicConfigProvider).value);
});

class MapMarker {
  const MapMarker({required this.point, required this.label, required this.icon, required this.color});

  final LatLng point;
  final String label;
  final IconData icon;
  final Color color;
}

/// A tile map with labelled markers (flutter_map).
class HelmMap extends StatelessWidget {
  const HelmMap({
    super.key,
    required this.tiles,
    required this.center,
    this.markers = const [],
    this.zoom = 12,
  });

  final MapTiles tiles;
  final LatLng center;
  final List<MapMarker> markers;
  final double zoom;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Map showing ${markers.map((m) => m.label).join(', ')}',
      child: FlutterMap(
        options: MapOptions(initialCenter: center, initialZoom: zoom),
        children: [
          TileLayer(
            urlTemplate: tiles.urlTemplate,
            additionalOptions: tiles.options,
            userAgentPackageName: 'nz.co.helmmarine.helm_marine',
          ),
          MarkerLayer(
            markers: [
              for (final m in markers)
                Marker(
                  point: m.point,
                  width: 40,
                  height: 40,
                  child: Tooltip(message: m.label, child: Icon(m.icon, color: m.color, size: 32)),
                ),
            ],
          ),
          RichAttributionWidget(attributions: [TextSourceAttribution(tiles.attribution)]),
        ],
      ),
    );
  }
}
