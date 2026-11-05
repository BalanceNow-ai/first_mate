import 'package:flutter/material.dart';
import 'package:helm_marine/core/models/boat_db.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

const _monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/// The server's HIN decode, shown as a *suggestion*. Nothing is applied to
/// the form unless the user taps one of the "Use …" actions; the manufacturer
/// is shown only when the server identified it.
class HinSuggestionCard extends StatelessWidget {
  const HinSuggestionCard({
    super.key,
    required this.decode,
    this.currentYear,
    this.currentMake,
    this.onUseYear,
    this.onUseMake,
    this.onUseNormalized,
    this.onDismiss,
  });

  final HinDecode decode;
  final int? currentYear;
  final String? currentMake;
  final ValueChanged<int>? onUseYear;
  final ValueChanged<String>? onUseMake;
  final ValueChanged<String>? onUseNormalized;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final d = decode;
    final theme = Theme.of(context);
    final (Color color, IconData icon, String title) = switch (d.status) {
      'valid' => (HelmTheme.success, Icons.check_circle_outline, 'HIN decoded'),
      'unrecognised' => (HelmTheme.warning, Icons.help_outline, 'HIN not recognised'),
      _ => (HelmTheme.error, Icons.error_outline, 'HIN could not be decoded'),
    };
    final rows = <(String, String)>[
      if (d.normalized != null) ('Normalised', d.normalized!),
      if (d.format != null) ('Format', d.format!.replaceAll('_', ' ')),
      if (d.countryCode != null) ('Country', d.countryCode!),
      if (d.mic != null) ('Manufacturer code', d.mic!),
      if (d.manufacturer != null)
        ('Manufacturer', '${d.manufacturer!.name}${d.manufacturer!.isSynthetic ? ' (synthetic test data)' : ''}')
      else if (d.valid)
        ('Manufacturer', 'Not identified'),
      if (d.modelYear != null) ('Model year', '${d.modelYear}'),
      if (d.productionYear != null)
        ('Built', [
          if (d.productionMonth != null) _monthNames[d.productionMonth! - 1],
          '${d.productionYear}',
        ].join(' ')),
      if (d.valid) ('Confidence', '${(d.confidence * 100).round()}%'),
    ];
    final suggestions = <Widget>[
      if (d.modelYear != null && d.modelYear != currentYear && onUseYear != null)
        OutlinedButton(
          onPressed: () => onUseYear!(d.modelYear!),
          child: Text('Use year ${d.modelYear}'),
        ),
      if (d.manufacturer != null && d.manufacturer!.name != currentMake && onUseMake != null)
        OutlinedButton(
          onPressed: () => onUseMake!(d.manufacturer!.name),
          child: Text('Use make ${d.manufacturer!.name}'),
        ),
      if (d.normalized != null && d.normalized != d.input && onUseNormalized != null)
        OutlinedButton(
          onPressed: () => onUseNormalized!(d.normalized!),
          child: Text('Use ${d.normalized}'),
        ),
    ];
    return Semantics(
      container: true,
      liveRegion: true,
      child: Card(
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: color.withValues(alpha: 0.5)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(icon, color: color),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(title,
                        style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                  ),
                  if (onDismiss != null)
                    IconButton(
                      icon: const Icon(Icons.close),
                      tooltip: 'Dismiss HIN suggestion',
                      onPressed: onDismiss,
                    ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                d.isInvalid
                    ? 'Check the number, or enter your vessel details manually.'
                    : d.note ?? 'Suggestion only — it does not change the details you entered.',
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: 8),
              for (final (label, value) in rows)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 140,
                        child: Text(label, style: const TextStyle(color: HelmTheme.mutedText)),
                      ),
                      Expanded(child: Text(value)),
                    ],
                  ),
                ),
              for (final w in d.warnings)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.warning_amber, size: 18, color: HelmTheme.warning),
                      const SizedBox(width: 6),
                      Expanded(child: Text(w)),
                    ],
                  ),
                ),
              if (suggestions.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: suggestions),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
