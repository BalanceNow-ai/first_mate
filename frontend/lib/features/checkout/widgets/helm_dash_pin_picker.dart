import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:helm_marine/core/models/shipping.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/helm_dash/widgets/sea_map.dart';
import 'package:latlong2/latlong.dart';

/// Chooses the Helm Dash delivery position: tap the map or drag the pin, or
/// type the coordinates. The pin can only be placed inside an enabled
/// operating area; a drop outside is refused with an explanation.
class HelmDashPinPicker extends StatefulWidget {
  const HelmDashPinPicker({super.key, required this.areas, required this.value, required this.onChanged});

  final List<OperatingAreaSummary> areas;
  final LatLng? value;
  final ValueChanged<LatLng> onChanged;

  @override
  State<HelmDashPinPicker> createState() => _HelmDashPinPickerState();
}

class _HelmDashPinPickerState extends State<HelmDashPinPicker> {
  final _mapController = MapController();
  final _mapKey = GlobalKey();
  final _lat = TextEditingController();
  final _lng = TextEditingController();
  String? _message;
  LatLng? _dragging;

  @override
  void initState() {
    super.initState();
    _syncFields(widget.value);
  }

  @override
  void didUpdateWidget(HelmDashPinPicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != oldWidget.value) _syncFields(widget.value);
  }

  @override
  void dispose() {
    _lat.dispose();
    _lng.dispose();
    _mapController.dispose();
    super.dispose();
  }

  void _syncFields(LatLng? p) {
    if (p == null) return;
    _lat.text = p.latitude.toStringAsFixed(5);
    _lng.text = p.longitude.toStringAsFixed(5);
  }

  LatLng get _center {
    if (widget.value != null) return widget.value!;
    if (widget.areas.isNotEmpty) return LatLng(widget.areas.first.centerLat, widget.areas.first.centerLng);
    return haurakiGulf;
  }

  bool _place(LatLng p) {
    final area = areaContaining(widget.areas, p);
    if (area == null) {
      setState(() => _message = 'Helm Dash only delivers inside '
          '${widget.areas.isEmpty ? 'its operating areas' : widget.areas.map((a) => a.name).join(', ')}. '
          'Move the pin inside the shaded area.');
      _syncFields(widget.value);
      return false;
    }
    setState(() => _message = null);
    widget.onChanged(p);
    return true;
  }

  void _applyTyped() {
    final lat = double.tryParse(_lat.text.trim());
    final lng = double.tryParse(_lng.text.trim());
    if (lat == null || lng == null || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setState(() => _message = 'Enter a latitude between -90 and 90 and a longitude between -180 and 180.');
      return;
    }
    final p = LatLng(lat, lng);
    if (_place(p)) _mapController.move(p, _mapController.camera.zoom);
  }

  LatLng? _toLatLng(Offset global) {
    final box = _mapKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return null;
    return _mapController.camera.screenOffsetToLatLng(box.globalToLocal(global));
  }

  @override
  Widget build(BuildContext context) {
    final pin = _dragging ?? widget.value;
    final inside = pin == null ? null : areaContaining(widget.areas, pin);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Tap the map or drag the pin to where your vessel will be. '
          'Shaded circles are the Helm Dash operating areas.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        SizedBox(
          key: _mapKey,
          height: 300,
          child: SeaMap(
            mapController: _mapController,
            center: _center,
            zoom: 9,
            areas: widget.areas,
            semanticLabel: pin == null
                ? 'Helm Dash delivery map. No position chosen yet.'
                : 'Helm Dash delivery map. Pin at ${pin.latitude.toStringAsFixed(4)}, ${pin.longitude.toStringAsFixed(4)}',
            onTap: _place,
            markers: [
              if (pin != null)
                SeaMarker(point: pin, label: 'Delivery position', icon: Icons.location_pin, color: HelmTheme.coral),
            ],
            markerBuilder: (m) => GestureDetector(
              behavior: HitTestBehavior.opaque,
              onPanStart: (_) => setState(() => _dragging = widget.value),
              onPanUpdate: (d) {
                final p = _toLatLng(d.globalPosition);
                if (p != null) setState(() => _dragging = p);
              },
              onPanEnd: (_) {
                final p = _dragging;
                setState(() => _dragging = null);
                if (p != null) _place(p);
              },
              child: Tooltip(
                message: 'Drag to move the delivery position',
                child: Icon(m.icon, color: m.color, size: 44),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _lat,
                decoration: const InputDecoration(labelText: 'Latitude'),
                keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[-0-9.]'))],
                onSubmitted: (_) => _applyTyped(),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: _lng,
                decoration: const InputDecoration(labelText: 'Longitude'),
                keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[-0-9.]'))],
                onSubmitted: (_) => _applyTyped(),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton(onPressed: _applyTyped, child: const Text('Set pin')),
          ],
        ),
        if (_message != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Semantics(
              liveRegion: true,
              child: Text(_message!, style: const TextStyle(color: HelmTheme.error)),
            ),
          )
        else if (inside != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('Inside ${inside.name}', style: const TextStyle(color: HelmTheme.success)),
          ),
      ],
    );
  }
}
