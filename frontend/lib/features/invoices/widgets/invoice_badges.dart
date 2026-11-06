import 'package:flutter/material.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/features/invoices/data/invoice_models.dart';
import 'package:intl/intl.dart';

/// A small labelled pill (icon + text) that reads well to screen readers.
class InfoPill extends StatelessWidget {
  const InfoPill({super.key, required this.label, required this.color, this.icon, this.semanticsLabel});

  final String label;
  final Color color;
  final IconData? icon;
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticsLabel ?? label,
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withValues(alpha: 0.5)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 14, color: color), const SizedBox(width: 4)],
            Flexible(
              child: Text(label,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(color: color, fontWeight: FontWeight.w600)),
            ),
          ],
        ),
      ),
    );
  }
}

class SourceBadge extends StatelessWidget {
  const SourceBadge(this.source, {super.key});

  final ValueSource source;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (source) {
      ValueSource.extracted => (HelmTheme.ocean, Icons.document_scanner_outlined),
      ValueSource.ownerCorrected => (HelmTheme.secondary, Icons.edit_outlined),
      ValueSource.ownerConfirmed => (HelmTheme.success, Icons.check_circle_outline),
      ValueSource.ownerEntered => (HelmTheme.secondary, Icons.keyboard_outlined),
      ValueSource.notExtracted => (HelmTheme.mutedText, Icons.help_outline),
    };
    return InfoPill(label: source.label, color: color, icon: icon);
  }
}

String certaintyLabel(String certainty) => switch (certainty) {
      'high' => 'Clearly read',
      'medium' => 'Probably right',
      'low' => 'Hard to read',
      _ => 'Certainty unknown',
    };

class CertaintyChip extends StatelessWidget {
  const CertaintyChip(this.certainty, {super.key});

  final String certainty;

  @override
  Widget build(BuildContext context) {
    final color = switch (certainty) {
      'high' => HelmTheme.success,
      'medium' => HelmTheme.ocean,
      'low' => HelmTheme.warning,
      _ => HelmTheme.mutedText,
    };
    return InfoPill(
      label: certaintyLabel(certainty),
      color: color,
      icon: Icons.visibility_outlined,
      semanticsLabel: 'Reading certainty: ${certaintyLabel(certainty)}',
    );
  }
}

class NeedsConfirmationChip extends StatelessWidget {
  const NeedsConfirmationChip({super.key});

  @override
  Widget build(BuildContext context) => const InfoPill(
        label: 'Needs your confirmation',
        color: HelmTheme.warning,
        icon: Icons.warning_amber_rounded,
      );
}

/// "Provisional until reviewed" notice.
class ProvisionalBanner extends StatelessWidget {
  const ProvisionalBanner({super.key, this.onReview});

  final VoidCallback? onReview;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: HelmTheme.warning.withValues(alpha: 0.08),
      child: ListTile(
        leading: const Icon(Icons.pending_actions, color: HelmTheme.warning),
        title: const Text('Provisional until reviewed'),
        subtitle: const Text(
            'Check the details against the document and mark them reviewed. Until then, the checks and '
            'comparisons below are provisional.'),
        trailing: onReview == null
            ? null
            : TextButton(onPressed: onReview, child: const Text('Review')),
      ),
    );
  }
}

/// A section heading with an optional subtitle.
class SectionHeading extends StatelessWidget {
  const SectionHeading(this.title, {super.key, this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 20, bottom: 8),
      child: Semantics(
        header: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
            if (subtitle != null) ...[
              const SizedBox(height: 2),
              Text(subtitle!, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText)),
            ],
          ],
        ),
      ),
    );
  }
}

final _dateFormat = DateFormat('d MMM yyyy, h:mm a');

/// Local date/time for a UTC timestamp (NZ English).
String formatWhen(DateTime when) => _dateFormat.format(when.toLocal());

/// True for an optimistic-concurrency conflict (someone else changed it).
bool isVersionConflict(Object error) => ApiError.from(error)?.code == 'version_conflict';

/// Shows the server's message, offering a reload for a version conflict.
Future<void> showMutationError(
  BuildContext context,
  Object error, {
  required Future<void> Function() onReload,
  ScaffoldMessengerState? messenger,
}) async {
  if (!context.mounted) return;
  if (isVersionConflict(error)) {
    final reload = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('This invoice has changed'),
        content: const Text(
            'It was changed somewhere else (perhaps in another window) since you opened it. Reload to see the '
            'latest details, then make your change again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Reload')),
        ],
      ),
    );
    if (reload == true) await onReload();
    return;
  }
  (messenger ?? ScaffoldMessenger.of(context)).showSnackBar(SnackBar(content: Text(describeError(error)), backgroundColor: HelmTheme.error, behavior: SnackBarBehavior.floating));
}
