import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/monitoring/monitoring.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/vessels/data/garage_api.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:helm_marine/features/vessels/widgets/hin_suggestion.dart';
import 'package:helm_marine/features/vessels/widgets/lookup_field.dart';

/// Add / edit a vessel using the canonical server fields.
class VesselFormScreen extends ConsumerWidget {
  const VesselFormScreen({super.key, this.vesselId, this.fromOnboarding = false});

  final String? vesselId;
  final bool fromOnboarding;

  bool get isEditing => vesselId != null;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final title = Text(isEditing ? 'Edit Vessel' : 'Add Vessel');
    if (!isEditing) {
      return Scaffold(
        appBar: AppBar(title: title),
        body: VesselForm(fromOnboarding: fromOnboarding),
      );
    }
    final vessel = ref.watch(vesselDetailProvider(vesselId!));
    return Scaffold(
      appBar: AppBar(title: title),
      body: vessel.when(
        data: (v) => VesselForm(initial: v),
        loading: () => const LoadingView(message: 'Loading vessel'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load this vessel',
          onRetry: () => ref.invalidate(vesselDetailProvider(vesselId!)),
        ),
      ),
    );
  }
}

class VesselForm extends ConsumerStatefulWidget {
  const VesselForm({super.key, this.initial, this.fromOnboarding = false});

  final Vessel? initial;
  final bool fromOnboarding;

  @override
  ConsumerState<VesselForm> createState() => _VesselFormState();
}

class _VesselFormState extends ConsumerState<VesselForm> {
  final _formKey = GlobalKey<FormState>();
  late final Map<String, TextEditingController> _c;
  String? _hullType;
  String? _propulsionType;
  bool _isPrimary = false;
  bool _submitting = false;
  String? _formError;

  /// The latest HIN decode (a suggestion; never applied automatically).
  HinDecode? _hin;
  bool _decoding = false;
  String? _hinError;

  /// Boat-database manufacturer chosen from the make suggestions (assist only).
  BoatManufacturer? _maker;
  List<BoatModel>? _makerModels;
  Map<String, String> _serverErrors = const {};

  static const _textFields = [
    'nickname', 'make', 'model', 'year', 'length_ft', 'primary_use', 'hin',
    'engine_make', 'engine_model', 'engine_year', 'engine_hours', 'engine_serial',
  ];

  @override
  void initState() {
    super.initState();
    final v = widget.initial;
    String s(Object? value) => value == null ? '' : '$value';
    final values = <String, String>{
      'nickname': s(v?.nickname),
      'make': s(v?.make),
      'model': s(v?.model),
      'year': s(v?.year),
      'length_ft': s(v?.lengthFt),
      'primary_use': s(v?.primaryUse),
      'hin': s(v?.hin),
      'engine_make': s(v?.engineMake),
      'engine_model': s(v?.engineModel),
      'engine_year': s(v?.engineYear),
      'engine_hours': s(v?.engineHours),
      'engine_serial': s(v?.engineSerial),
    };
    _c = {for (final f in _textFields) f: TextEditingController(text: values[f])};
    _hullType = hullTypes.contains(v?.hullType) ? v?.hullType : null;
    _propulsionType = propulsionTypes.contains(v?.propulsionType) ? v?.propulsionType : null;
    _isPrimary = v?.isPrimary ?? false;
    final stored = v?.hinDecoded;
    if (stored != null) {
      try {
        _hin = HinDecode.fromJson(stored);
      } on FormatException {
        _hin = null; // An older stored shape: just don't show a suggestion.
      }
    }
  }

  // --- HIN decode (suggestion only) ------------------------------------------

  Future<void> _decodeHin() async {
    final hin = _text('hin');
    if (hin == null) {
      setState(() => _hinError = 'Enter a HIN to decode');
      return;
    }
    setState(() {
      _decoding = true;
      _hinError = null;
    });
    try {
      final result = await ref.read(garageApiProvider).decodeHin(hin);
      if (mounted) setState(() => _hin = result);
    } catch (e) {
      if (mounted) setState(() => _hinError = 'Could not decode the HIN: ${describeError(e)}');
    } finally {
      if (mounted) setState(() => _decoding = false);
    }
  }

  void _useValue(String field, String value) {
    setState(() => _c[field]!.text = value);
  }

  // --- boat database typeahead (assist only) ----------------------------------

  Future<List<BoatManufacturer>> _searchMakers(String text) async {
    if (text.length < 2) return const [];
    return ref.read(garageApiProvider).manufacturers(q: text);
  }

  Future<List<BoatModel>> _searchModels(String text) async {
    final maker = _maker;
    if (maker == null || maker.name != _c['make']!.text.trim()) return const [];
    final models = _makerModels ??= await ref.read(garageApiProvider).models(maker.id);
    final needle = text.toLowerCase();
    return [for (final m in models) if (m.name.toLowerCase().contains(needle)) m];
  }

  String? get _yearHint {
    final model = _c['model']!.text.trim();
    for (final m in _makerModels ?? const <BoatModel>[]) {
      if (m.name == model && m.years.isNotEmpty) return 'Boat database years: ${m.years.join(', ')}';
    }
    return null;
  }

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  String? _text(String field) {
    final v = _c[field]!.text.trim();
    return v.isEmpty ? null : v;
  }

  VesselDraft _draft() => VesselDraft(
        nickname: _text('nickname')!,
        make: _text('make')!,
        model: _text('model')!,
        year: int.parse(_text('year')!),
        isPrimary: _isPrimary,
        hin: _text('hin')?.toUpperCase(),
        hullType: _hullType,
        lengthFt: _text('length_ft') == null ? null : double.parse(_text('length_ft')!),
        primaryUse: _text('primary_use'),
        propulsionType: _propulsionType,
        engineMake: _text('engine_make'),
        engineModel: _text('engine_model'),
        engineYear: _text('engine_year') == null ? null : int.parse(_text('engine_year')!),
        engineSerial: _text('engine_serial'),
        engineHours: _text('engine_hours') == null ? null : int.parse(_text('engine_hours')!),
      );

  Future<void> _submit() async {
    setState(() {
      _serverErrors = const {};
      _formError = null;
    });
    if (!_formKey.currentState!.validate()) return;
    setState(() => _submitting = true);
    final notifier = ref.read(vesselListProvider.notifier);
    try {
      final draft = _draft();
      final initial = widget.initial;
      final Vessel saved;
      if (initial != null) {
        saved = await notifier.updateVessel(initial.id, draft);
      } else {
        saved = await notifier.createVessel(draft);
        ref.read(monitoringProvider).capture('vessel_created');
      }
      if (!mounted) return;
      context.go(widget.fromOnboarding ? '/' : '/vessels/${saved.id}');
    } catch (e) {
      final api = ApiError.from(e);
      if (!mounted) return;
      setState(() {
        _formError = describeError(e);
        _serverErrors = {
          for (final fe in api?.errors ?? const <FieldError>[])
            if (fe.field.isNotEmpty) fe.field: fe.msg,
        };
      });
      // Show the server's field errors on their fields after this rebuild.
      WidgetsBinding.instance.addPostFrameCallback((_) => _formKey.currentState?.validate());
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  // --- validators (mirror the server's VesselCreate bounds) -----------------

  String? _server(String field) => _serverErrors[field];

  FormFieldValidator<String> _required(String field, String label, {int max = 100}) => (v) {
        final t = v?.trim() ?? '';
        if (t.isEmpty) return '$label is required';
        if (t.length > max) return 'At most $max characters';
        return _server(field);
      };

  FormFieldValidator<String> _maxLen(String field, int max) => (v) {
        if ((v?.trim().length ?? 0) > max) return 'At most $max characters';
        return _server(field);
      };

  FormFieldValidator<String> _intRange(String field, String label, int min, int max,
          {bool required = false}) =>
      (v) {
        final t = v?.trim() ?? '';
        if (t.isEmpty) return required ? '$label is required' : _server(field);
        final n = int.tryParse(t);
        if (n == null) return 'Enter a whole number';
        if (n < min || n > max) return '$label must be between $min and $max';
        return _server(field);
      };

  String? _length(String? v) {
    final t = v?.trim() ?? '';
    if (t.isEmpty) return _server('length_ft');
    final n = double.tryParse(t);
    if (n == null) return 'Enter a number, e.g. 19.5';
    if (n <= 0 || n > 400) return 'Length must be more than 0 and at most 400 ft';
    return _server('length_ft');
  }

  Widget _field(String field, String label,
      {FormFieldValidator<String>? validator,
      TextInputType? keyboard,
      List<TextInputFormatter>? formatters,
      String? hint,
      TextCapitalization caps = TextCapitalization.none}) {
    return TextFormField(
      controller: _c[field],
      decoration: InputDecoration(labelText: label, hintText: hint),
      keyboardType: keyboard,
      inputFormatters: formatters,
      textCapitalization: caps,
      textInputAction: TextInputAction.next,
      validator: validator,
    );
  }

  Widget _pair(Widget a, Widget b) => LayoutBuilder(builder: (context, constraints) {
        if (constraints.maxWidth < 420) {
          return Column(children: [a, const SizedBox(height: 12), b]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: a),
          const SizedBox(width: 12),
          Expanded(child: b),
        ]);
      });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final digits = [FilteringTextInputFormatter.digitsOnly];
    final heading = theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold);
    return ContentWidth(
      child: Form(
        key: _formKey,
        child: FocusTraversalGroup(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Fixed slot: fields below must not shift when the error appears.
              _formError == null
                  ? const SizedBox.shrink()
                  : Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Semantics(
                        liveRegion: true,
                        child: Text(_formError!, style: TextStyle(color: theme.colorScheme.error)),
                      ),
                    ),
              Semantics(header: true, child: Text('Vessel', style: heading)),
              const SizedBox(height: 12),
              _field('nickname', 'Nickname *',
                  hint: 'e.g. Sea Biscuit',
                  caps: TextCapitalization.words,
                  validator: _required('nickname', 'Nickname')),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 480),
                    child: TextFormField(
                      controller: _c['hin'],
                      decoration: const InputDecoration(
                        labelText: 'HIN (hull identification number)',
                        helperText: 'Optional. Decode it to see what the number says.',
                      ),
                      textCapitalization: TextCapitalization.characters,
                      textInputAction: TextInputAction.next,
                      validator: _maxLen('hin', 20),
                      onFieldSubmitted: (_) => _decodeHin(),
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: _decoding ? null : _decodeHin,
                    icon: _decoding
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2, semanticsLabel: 'Decoding'),
                          )
                        : const Icon(Icons.qr_code_scanner),
                    label: const Text('Decode HIN'),
                  ),
                ],
              ),
              if (_hinError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Semantics(
                    liveRegion: true,
                    child: Text(_hinError!, style: TextStyle(color: theme.colorScheme.error)),
                  ),
                ),
              if (_hin != null) ...[
                const SizedBox(height: 8),
                HinSuggestionCard(
                  decode: _hin!,
                  currentYear: int.tryParse(_c['year']!.text.trim()),
                  currentMake: _c['make']!.text.trim(),
                  onUseYear: (y) => _useValue('year', '$y'),
                  onUseMake: (m) => _useValue('make', m),
                  onUseNormalized: (h) => _useValue('hin', h),
                  onDismiss: () => setState(() => _hin = null),
                ),
              ],
              const SizedBox(height: 12),
              _pair(
                LookupField<BoatManufacturer>(
                  controller: _c['make']!,
                  label: 'Make *',
                  hint: 'e.g. Haines Hunter',
                  textCapitalization: TextCapitalization.words,
                  search: _searchMakers,
                  display: (m) => m.name,
                  subtitle: (m) => [
                    if (m.country != null) m.country!,
                    '${m.modelCount} models in the boat database',
                    if (m.isSynthetic) 'synthetic test data',
                  ].join(' · '),
                  onSelected: (m) => setState(() {
                    _maker = m;
                    _makerModels = null;
                  }),
                  validator: _required('make', 'Make'),
                ),
                LookupField<BoatModel>(
                  controller: _c['model']!,
                  label: 'Model *',
                  hint: 'e.g. SF600',
                  search: _searchModels,
                  display: (m) => m.name,
                  subtitle: (m) => m.years.isEmpty ? null : 'Years: ${m.years.join(', ')}',
                  onSelected: (_) => setState(() {}),
                  validator: _required('model', 'Model'),
                ),
              ),
              const SizedBox(height: 12),
              _pair(
                TextFormField(
                  controller: _c['year'],
                  decoration: InputDecoration(labelText: 'Year *', helperText: _yearHint),
                  keyboardType: TextInputType.number,
                  inputFormatters: digits,
                  textInputAction: TextInputAction.next,
                  validator: _intRange('year', 'Year', 1900, 2100, required: true),
                ),
                _field('length_ft', 'Length (ft)',
                    keyboard: const TextInputType.numberWithOptions(decimal: true),
                    formatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
                    validator: _length),
              ),
              const SizedBox(height: 12),
              _pair(
                DropdownButtonFormField<String>(
                  initialValue: _hullType,
                  decoration: const InputDecoration(labelText: 'Hull type'),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Not specified')),
                    for (final h in hullTypes) DropdownMenuItem(value: h, child: Text(enumLabel(h))),
                  ],
                  onChanged: (v) => setState(() => _hullType = v),
                  validator: (_) => _server('hull_type'),
                ),
                DropdownButtonFormField<String>(
                  initialValue: _propulsionType,
                  decoration: const InputDecoration(labelText: 'Propulsion'),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Not specified')),
                    for (final p in propulsionTypes)
                      DropdownMenuItem(value: p, child: Text(enumLabel(p))),
                  ],
                  onChanged: (v) => setState(() => _propulsionType = v),
                  validator: (_) => _server('propulsion_type'),
                ),
              ),
              const SizedBox(height: 12),
              _field('primary_use', 'Primary use',
                  hint: 'e.g. fishing', validator: _maxLen('primary_use', 60)),
              const SizedBox(height: 24),
              Semantics(header: true, child: Text('Engine', style: heading)),
              const SizedBox(height: 4),
              Text('Engine details let us verify which parts fit.',
                  style: theme.textTheme.bodySmall),
              const SizedBox(height: 12),
              _pair(
                _field('engine_make', 'Engine make',
                    hint: 'e.g. Mercury',
                    caps: TextCapitalization.words,
                    validator: _maxLen('engine_make', 60)),
                _field('engine_model', 'Engine model',
                    hint: 'e.g. F150', validator: _maxLen('engine_model', 60)),
              ),
              const SizedBox(height: 12),
              _pair(
                _field('engine_year', 'Engine year',
                    keyboard: TextInputType.number,
                    formatters: digits,
                    validator: _intRange('engine_year', 'Engine year', 1900, 2100)),
                _field('engine_hours', 'Engine hours',
                    keyboard: TextInputType.number,
                    formatters: digits,
                    validator: _intRange('engine_hours', 'Engine hours', 0, 100000)),
              ),
              const SizedBox(height: 12),
              _field('engine_serial', 'Engine serial number',
                  validator: _maxLen('engine_serial', 60)),
              const SizedBox(height: 12),
              SwitchListTile(
                title: const Text('Primary vessel'),
                subtitle: const Text('Used for fitment checks and recommendations'),
                value: _isPrimary,
                onChanged: (v) => setState(() => _isPrimary = v),
                contentPadding: EdgeInsets.zero,
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                          semanticsLabel: 'Saving',
                        ),
                      )
                    : Text(widget.initial != null ? 'Save changes' : 'Add vessel'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
