import 'package:flutter/material.dart';
import 'package:helm_marine/core/models/product.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// Shows the server's fitment verdict for a product and vessel.
///
/// * `verified_fit` / `universal` → `Fits <vessel>`
/// * `verified_mismatch` → "Does not fit"
/// * `unknown` (and anything unrecognised) → "Fit unknown — not verified"
///
/// An unknown result is never presented as fitting.
class FitmentBadge extends StatelessWidget {
  const FitmentBadge({super.key, required this.fitment, this.vesselName, this.dense = false});

  final Fitment fitment;

  /// Short vessel name (nickname) for "Fits Sea Biscuit".
  final String? vesselName;
  final bool dense;

  static String labelFor(FitmentStatus status, String? vesselName) => switch (status) {
        FitmentStatus.verifiedFit ||
        FitmentStatus.universal =>
          vesselName == null || vesselName.isEmpty ? 'Fits your vessel' : 'Fits $vesselName',
        FitmentStatus.verifiedMismatch => 'Does not fit',
        FitmentStatus.unknown => 'Fit unknown — not verified',
      };

  @override
  Widget build(BuildContext context) {
    final status = fitment.status;
    final (Color color, IconData icon) = switch (status) {
      FitmentStatus.verifiedFit || FitmentStatus.universal => (HelmTheme.success, Icons.check_circle),
      FitmentStatus.verifiedMismatch => (HelmTheme.error, Icons.cancel),
      FitmentStatus.unknown => (HelmTheme.warning, Icons.help_outline),
    };
    final label = labelFor(status, vesselName);
    return Semantics(
      label: '$label. ${fitment.message}',
      excludeSemantics: true,
      child: Tooltip(
        message: fitment.message,
        child: Container(
          padding: EdgeInsets.symmetric(horizontal: dense ? 6 : 10, vertical: dense ? 2 : 6),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: color.withValues(alpha: 0.5)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: dense ? 14 : 18, color: color),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: HelmTheme.darken(color),
                    fontWeight: FontWeight.w600,
                    fontSize: dense ? 12 : 13,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
