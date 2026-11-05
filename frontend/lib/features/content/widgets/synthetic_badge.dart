import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// A small labelled pill (status, role, synthetic marker...).
class InfoPill extends StatelessWidget {
  const InfoPill({super.key, required this.label, this.color = HelmTheme.mutedText, this.icon, this.tooltip});

  final String label;
  final Color color;
  final IconData? icon;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final pill = Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 14, color: HelmTheme.darken(color, 0.1)), const SizedBox(width: 4)],
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: HelmTheme.darken(color, 0.1)),
            ),
          ),
        ],
      ),
    );
    return tooltip == null ? pill : Tooltip(message: tooltip!, child: pill);
  }
}

/// Marks data that is a synthetic local-development fixture, not real content.
class SyntheticBadge extends StatelessWidget {
  const SyntheticBadge({super.key, this.label = 'Synthetic test data'});

  final String label;

  @override
  Widget build(BuildContext context) => InfoPill(
        label: label,
        icon: Icons.science_outlined,
        color: HelmTheme.warning,
        tooltip: 'Synthetic fixture for local development and testing — not real guidance or a real offer.',
      );
}
