import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';

enum Tone { neutral, info, good, warn, bad }

Color toneColor(Tone tone) => switch (tone) {
  Tone.neutral => HelmTheme.mutedText,
  Tone.info => HelmTheme.primary,
  Tone.good => HelmTheme.success,
  Tone.warn => HelmTheme.warning,
  Tone.bad => HelmTheme.error,
};

/// A plain, labelled status/provenance badge (colour is never the only signal).
class StatusBadge extends StatelessWidget {
  const StatusBadge(this.label, {super.key, this.tone = Tone.neutral, this.icon, this.semanticPrefix});

  final String label;
  final Tone tone;
  final IconData? icon;
  final String? semanticPrefix;

  @override
  Widget build(BuildContext context) {
    final color = toneColor(tone);
    return Semantics(
      label: semanticPrefix == null ? label : '$semanticPrefix: $label',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withValues(alpha: 0.55)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 14, color: HelmTheme.darken(color)), const SizedBox(width: 4)],
            Flexible(
              child: Text(
                label,
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: HelmTheme.darken(color)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

Tone provenanceTone(String badge) => switch (badge) {
  'contractor_confirmed' || 'source_verified' => Tone.good,
  'owner_measured' || 'owner_declared' => Tone.info,
  'model_suggested' || 'suggested' => Tone.warn,
  'rejected' => Tone.bad,
  _ => Tone.neutral,
};

/// The plain provenance badge ("Suggested", "Owner measured", "Contractor confirmed", "Unknown", "Superseded").
class ProvenanceBadge extends StatelessWidget {
  const ProvenanceBadge(this.state, {super.key});

  final String state;

  @override
  Widget build(BuildContext context) =>
      StatusBadge(provenanceLabel(state), tone: provenanceTone(state), semanticPrefix: 'Provenance');
}

Tone jobStatusTone(String s) => switch (s) {
  'completed' => Tone.good,
  'cancelled' || 'archived' => Tone.neutral,
  'draft' => Tone.neutral,
  _ => Tone.info,
};

/// A titled card section.
class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, required this.children, this.trailing, this.subtitle});

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      explicitChildNodes: true,
      child: Card(
        margin: const EdgeInsets.only(bottom: 16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Semantics(
                      header: true,
                      container: true,
                      child: Text(
                        title,
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                  ?trailing,
                ],
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Semantics(container: true, child: Text(subtitle!, style: const TextStyle(color: HelmTheme.mutedText))),
              ],
              const SizedBox(height: 8),
              for (final c in children) Semantics(container: true, child: c),
            ],
          ),
        ),
      ),
    );
  }
}

/// An informational note (limitations, honest unavailable states).
class InfoNote extends StatelessWidget {
  const InfoNote(this.text, {super.key, this.tone = Tone.info, this.icon = Icons.info_outline});

  final String text;
  final Tone tone;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final color = toneColor(tone);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: HelmTheme.darken(color), size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

/// Label/value row.
class FactRow extends StatelessWidget {
  const FactRow(this.label, this.value, {super.key});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
            child: Text(label, style: const TextStyle(color: HelmTheme.mutedText)),
          ),
          Expanded(
            child: Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
          ),
        ],
      ),
    );
  }
}

/// Renders an [AsyncValue] with the app's loading/error/retry views.
class AsyncSection<T> extends StatelessWidget {
  const AsyncSection({super.key, required this.value, required this.builder, this.onRetry, this.errorTitle});

  final AsyncValue<T> value;
  final Widget Function(T data) builder;
  final VoidCallback? onRetry;
  final String? errorTitle;

  @override
  Widget build(BuildContext context) {
    return value.when(
      data: builder,
      loading: () => const Padding(padding: EdgeInsets.all(24), child: LoadingView()),
      error: (e, _) => ErrorView(error: e, title: errorTitle ?? friendlyTitle(e), onRetry: onRetry),
    );
  }
}

/// A page-level title for common access failures.
String friendlyTitle(Object error) {
  final api = ApiError.from(error);
  if (api == null) return 'Something went wrong';
  if (api.statusCode == 404) return 'Not found, or not shared with you';
  if (api.code == 'live_updates_not_shared') return 'This isn’t in the brief the owner published';
  if (api.code == 'section_not_shared' || api.statusCode == 403) {
    return 'This part of the job has not been shared with you';
  }
  return 'Something went wrong';
}

/// Runs a job mutation with consistent handling: a 409 version conflict asks
/// the person to reload; other failures show the server's message. Returns
/// the result, or null when it failed.
Future<T?> runJobAction<T>(
  BuildContext context,
  WidgetRef ref,
  String jobId,
  Future<T> Function() action, {
  String? success,
}) async {
  try {
    final result = await action();
    if (!context.mounted) return result;
    refreshServiceJob(ref, jobId);
    if (success != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(success)));
    }
    return result;
  } catch (e) {
    if (!context.mounted) return null;
    final api = ApiError.from(e);
    if (api != null &&
        (api.code == 'version_conflict' || api.code == 'preview_outdated' || api.code == 'brief_outdated')) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('This changed while you were looking'),
          content: Text('${api.detail}\n\nReload to see the latest version, then try again.'),
          actions: [
            FilledButton(
              onPressed: () {
                Navigator.pop(dialogContext);
                refreshServiceJob(ref, jobId);
              },
              child: const Text('Reload'),
            ),
          ],
        ),
      );
      return null;
    }
    showErrorSnackBar(context, e);
    return null;
  }
}

/// A large, labelled action button.
class ActionButton extends StatelessWidget {
  const ActionButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.filled = false,
    this.tone,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool filled;
  final Tone? tone;

  @override
  Widget build(BuildContext context) {
    final style = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(48, HelmTheme.minTapTarget)),
      foregroundColor: tone == null || filled ? null : WidgetStatePropertyAll(toneColor(tone!)),
    );
    final child = Text(label);
    if (filled) {
      return icon == null
          ? FilledButton(onPressed: onPressed, style: style, child: child)
          : FilledButton.icon(onPressed: onPressed, style: style, icon: Icon(icon), label: child);
    }
    return icon == null
        ? OutlinedButton(onPressed: onPressed, style: style, child: child)
        : OutlinedButton.icon(onPressed: onPressed, style: style, icon: Icon(icon), label: child);
  }
}

/// Asks for optional or required text in a dialog. Returns null on cancel.
Future<String?> promptText(
  BuildContext context, {
  required String title,
  required String label,
  String? message,
  String confirm = 'Save',
  bool required = true,
  int maxLines = 3,
  int maxLength = 2000,
  String? initial,
}) {
  final controller = TextEditingController(text: initial);
  final formKey = GlobalKey<FormState>();
  return showDialog<String>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(title),
      content: Form(
        key: formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (message != null) ...[Text(message), const SizedBox(height: 12)],
            TextFormField(
              controller: controller,
              autofocus: true,
              maxLines: maxLines,
              maxLength: maxLength,
              decoration: InputDecoration(labelText: label),
              validator: (v) => required && (v == null || v.trim().isEmpty) ? 'This is required' : null,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (formKey.currentState!.validate()) Navigator.pop(dialogContext, controller.text.trim());
          },
          child: Text(confirm),
        ),
      ],
    ),
  );
}

/// Yes/no confirmation.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String message,
  String confirm = 'Confirm',
  bool destructive = false,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
        FilledButton(
          style: destructive ? FilledButton.styleFrom(backgroundColor: HelmTheme.error) : null,
          onPressed: () => Navigator.pop(dialogContext, true),
          child: Text(confirm),
        ),
      ],
    ),
  );
  return ok == true;
}

/// A plain list of labelled strings ("Exposes: …").
class BulletList extends StatelessWidget {
  const BulletList(this.items, {super.key});

  final List<String> items;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final i in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('•  '),
                Expanded(child: Text(i)),
              ],
            ),
          ),
      ],
    );
  }
}

String sectionsSummary(List<String> sections) => sections.map(sectionLabel).join(' · ');
