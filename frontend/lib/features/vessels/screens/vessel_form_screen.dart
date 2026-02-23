import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/main.dart';

class VesselFormScreen extends ConsumerStatefulWidget {
  final String? vesselId;
  final bool fromOnboarding;

  const VesselFormScreen({super.key, this.vesselId, this.fromOnboarding = false});

  bool get isEditing => vesselId != null;

  @override
  ConsumerState<VesselFormScreen> createState() => _VesselFormScreenState();
}

class _VesselFormScreenState extends ConsumerState<VesselFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _makeController = TextEditingController();
  final _modelController = TextEditingController();
  final _yearController = TextEditingController();
  final _hullMaterialController = TextEditingController();
  final _lengthController = TextEditingController();
  final _engineTypeController = TextEditingController();
  final _engineMakeController = TextEditingController();
  final _engineModelController = TextEditingController();
  bool _isPrimary = false;
  bool _isSubmitting = false;
  bool _populated = false;

  @override
  void dispose() {
    _nameController.dispose();
    _makeController.dispose();
    _modelController.dispose();
    _yearController.dispose();
    _hullMaterialController.dispose();
    _lengthController.dispose();
    _engineTypeController.dispose();
    _engineMakeController.dispose();
    _engineModelController.dispose();
    super.dispose();
  }

  void _populateFromVessel() {
    if (widget.vesselId == null || _populated) return;
    final vesselState = ref.read(vesselDetailProvider(widget.vesselId!));
    vesselState.whenData((vessel) {
      _nameController.text = vessel.name;
      _makeController.text = vessel.make;
      _modelController.text = vessel.model;
      if (vessel.year != null) _yearController.text = vessel.year.toString();
      if (vessel.hullMaterial != null) {
        _hullMaterialController.text = vessel.hullMaterial!;
      }
      if (vessel.lengthFt != null) {
        _lengthController.text = vessel.lengthFt.toString();
      }
      if (vessel.engineType != null) {
        _engineTypeController.text = vessel.engineType!;
      }
      if (vessel.engineMake != null) {
        _engineMakeController.text = vessel.engineMake!;
      }
      if (vessel.engineModel != null) {
        _engineModelController.text = vessel.engineModel!;
      }
      _isPrimary = vessel.isPrimary;
      _populated = true;
    });
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isSubmitting = true);

    final data = <String, dynamic>{
      'name': _nameController.text.trim(),
      'make': _makeController.text.trim(),
      'model': _modelController.text.trim(),
      'is_primary': _isPrimary,
    };

    if (_yearController.text.isNotEmpty) {
      data['year'] = int.parse(_yearController.text.trim());
    }
    if (_hullMaterialController.text.isNotEmpty) {
      data['hull_material'] = _hullMaterialController.text.trim();
    }
    if (_lengthController.text.isNotEmpty) {
      data['length_ft'] = double.parse(_lengthController.text.trim());
    }
    if (_engineTypeController.text.isNotEmpty) {
      data['engine_type'] = _engineTypeController.text.trim();
    }
    if (_engineMakeController.text.isNotEmpty) {
      data['engine_make'] = _engineMakeController.text.trim();
    }
    if (_engineModelController.text.isNotEmpty) {
      data['engine_model'] = _engineModelController.text.trim();
    }

    try {
      final notifier = ref.read(vesselListProvider.notifier);
      if (widget.isEditing) {
        await notifier.updateVessel(widget.vesselId!, data);
      } else {
        await notifier.createVessel(data);
        posthog.capture(eventName: 'vessel_created', properties: {
          'make': data['make'],
          'model': data['model'],
        });
      }
      if (mounted) context.go(widget.fromOnboarding ? '/' : '/vessels');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to save vessel: $e'),
            backgroundColor: HelmTheme.error,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.isEditing) {
      // Watch the vessel detail to populate form
      ref.watch(vesselDetailProvider(widget.vesselId!));
      _populateFromVessel();
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.isEditing ? 'Edit Vessel' : 'Add Vessel'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Basic info
              Text('Basic Information',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              TextFormField(
                controller: _nameController,
                decoration: const InputDecoration(labelText: 'Vessel Name *'),
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Required' : null,
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _makeController,
                      decoration: const InputDecoration(labelText: 'Make *'),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Required' : null,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _modelController,
                      decoration: const InputDecoration(labelText: 'Model *'),
                      validator: (v) =>
                          (v == null || v.trim().isEmpty) ? 'Required' : null,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _yearController,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(labelText: 'Year'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _lengthController,
                      keyboardType: TextInputType.number,
                      decoration:
                          const InputDecoration(labelText: 'Length (ft)'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _hullMaterialController,
                decoration: const InputDecoration(
                  labelText: 'Hull Material',
                  hintText: 'e.g. Fibreglass, Aluminium',
                ),
              ),
              const SizedBox(height: 24),

              // Engine info
              Text('Engine',
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              TextFormField(
                controller: _engineTypeController,
                decoration: const InputDecoration(
                  labelText: 'Engine Type',
                  hintText: 'e.g. Outboard, Inboard, Sterndrive',
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _engineMakeController,
                      decoration:
                          const InputDecoration(labelText: 'Engine Make'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _engineModelController,
                      decoration:
                          const InputDecoration(labelText: 'Engine Model'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              // Primary toggle
              SwitchListTile(
                title: const Text('Set as Primary Vessel'),
                subtitle: const Text(
                    'Your primary vessel is used for personalised recommendations'),
                value: _isPrimary,
                onChanged: (v) => setState(() => _isPrimary = v),
                activeColor: HelmTheme.primary,
                contentPadding: EdgeInsets.zero,
              ),
              const SizedBox(height: 24),

              // Submit
              ElevatedButton(
                onPressed: _isSubmitting ? null : _handleSubmit,
                child: _isSubmitting
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : Text(widget.isEditing ? 'Save Changes' : 'Add Vessel'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
