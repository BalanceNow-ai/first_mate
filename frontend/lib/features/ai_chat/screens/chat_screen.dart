import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/api/api_error.dart';
import 'package:helm_marine/core/models/first_mate.dart';
import 'package:helm_marine/core/models/vessel.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/ai_chat/data/first_mate_api.dart';
import 'package:helm_marine/features/ai_chat/providers/chat_provider.dart';
import 'package:helm_marine/features/ai_chat/widgets/answer_widgets.dart';
import 'package:helm_marine/features/vessels/providers/vessel_provider.dart';
import 'package:intl/intl.dart';

const chatSuggestions = [
  'Which spark plug does my engine need?',
  'What oil does my engine need?',
  'Pre-season checklist',
  'Recommended safety gear',
];

/// First Mate chat: grounded answers with sources, fitment-checked products and
/// explicit cart actions, scoped to one of the user's vessels.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key, this.vesselId});

  /// The vessel the chat was opened for (`/vessels/:id/chat`), if any.
  final String? vesselId;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _input.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  ChatController get _chat => ref.read(chatProvider(widget.vesselId).notifier);

  Future<void> _send([String? text]) async {
    final message = (text ?? _input.text).trim();
    if (message.isEmpty || message.length > maxChatMessageChars) return;
    if (text == null) _input.clear();
    final future = _chat.send(message);
    _scrollToEnd();
    await future;
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatProvider(widget.vesselId));
    ref.listen(chatProvider(widget.vesselId).select((s) => s.messages.length), (_, _) => _scrollToEnd());

    return Scaffold(
      appBar: AppBar(
        title: const Text('First Mate'),
        actions: [
          Builder(
            builder: (context) => IconButton(
              icon: const Icon(Icons.history),
              tooltip: 'Conversations',
              onPressed: () => Scaffold.of(context).openEndDrawer(),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.add_comment_outlined),
            tooltip: 'New conversation',
            onPressed: state.sending ? null : _chat.newConversation,
          ),
        ],
      ),
      endDrawer: _ConversationDrawer(vesselKey: widget.vesselId),
      body: Column(
        children: [
          _VesselContextBar(vesselKey: widget.vesselId),
          const Divider(height: 1),
          Expanded(
            child: state.loadingConversation
                ? const LoadingView(message: 'Opening conversation')
                : state.isEmpty
                    ? _EmptyChat(onSuggestion: _send)
                    : ContentWidth(
                        maxWidth: 860,
                        child: ListView.builder(
                          controller: _scroll,
                          padding: const EdgeInsets.all(16),
                          itemCount: state.messages.length + (state.sending ? 1 : 0),
                          itemBuilder: (context, i) {
                            if (i == state.messages.length) return const _ThinkingBubble();
                            return _MessageBubble(entry: state.messages[i]);
                          },
                        ),
                      ),
          ),
          if (state.error != null)
            _ChatErrorBanner(
              error: state.error!,
              canRetry: state.messages.any((m) => m.failed),
              onRetry: _chat.retry,
              onDismiss: _chat.dismissError,
            ),
          _Composer(
            controller: _input,
            focusNode: _focus,
            sending: state.sending,
            onSend: () => _send(),
          ),
        ],
      ),
    );
  }
}

class _VesselContextBar extends ConsumerWidget {
  const _VesselContextBar({required this.vesselKey});

  final String? vesselKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(chatProvider(vesselKey));
    final vessels = ref.watch(vesselListProvider);
    final list = vessels.value ?? const <Vessel>[];
    Vessel? chosen;
    for (final v in list) {
      if (v.id == state.vesselId) chosen = v;
    }
    final answeredFor = state.lastTurn?.vessel;
    Vessel? primary;
    for (final v in list) {
      if (v.isPrimary) primary ??= v;
    }
    final String label;
    if (chosen != null) {
      label = 'Vessel: ${chosen.label}';
    } else if (answeredFor != null) {
      label = 'Vessel: ${answeredFor.label}';
    } else if (primary != null) {
      label = 'Vessel: ${primary.label} (primary)';
    } else if (vessels.isLoading) {
      label = 'Loading vessels…';
    } else {
      label = 'No vessel — answers are general';
    }

    return Material(
      color: HelmTheme.surface,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Row(
          children: [
            Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: ActionChip(
                  avatar: const Icon(Icons.directions_boat, size: 18),
                  tooltip: list.isEmpty ? 'Add a vessel' : 'Change vessel',
                  label: Text(label, overflow: TextOverflow.ellipsis),
                  onPressed: list.isEmpty
                      ? () => context.go('/vessels/new')
                      : () => _pickVessel(context, ref, list, chosen?.id ?? answeredFor?.id ?? primary?.id),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _pickVessel(BuildContext context, WidgetRef ref, List<Vessel> vessels, String? current) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(title: Text('Ask about which vessel?', style: TextStyle(fontWeight: FontWeight.bold))),
            for (final v in vessels)
              ListTile(
                leading: Icon(v.id == current ? Icons.radio_button_checked : Icons.radio_button_off),
                title: Text(v.nickname),
                subtitle: Text([
                  v.description,
                  if (v.engineMake != null) [v.engineMake, v.engineModel].whereType<String>().join(' '),
                ].join(' · ')),
                trailing: v.isPrimary ? const Text('Primary') : null,
                onTap: () => Navigator.of(context).pop(v.id),
              ),
          ],
        ),
      ),
    );
    if (picked != null) ref.read(chatProvider(vesselKey).notifier).selectVessel(picked);
  }
}

class _EmptyChat extends StatelessWidget {
  const _EmptyChat({required this.onSuggestion});

  final ValueChanged<String> onSuggestion;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.sailing, size: 56, color: HelmTheme.ocean),
              const SizedBox(height: 12),
              Semantics(
                header: true,
                child: Text('Ask your First Mate', style: Theme.of(context).textTheme.titleLarge),
              ),
              const SizedBox(height: 8),
              const Text(
                'Answers are based on admitted sources and your vessel. Parts are only shown as fitting '
                'when the fitment is verified.',
                textAlign: TextAlign.center,
                style: TextStyle(color: HelmTheme.mutedText),
              ),
              const SizedBox(height: 20),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                alignment: WrapAlignment.center,
                children: [
                  for (final s in chatSuggestions)
                    ActionChip(label: Text(s), onPressed: () => onSuggestion(s)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.entry});

  final ChatEntry entry;

  @override
  Widget build(BuildContext context) {
    if (entry.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 6),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: entry.failed ? HelmTheme.error.withValues(alpha: 0.12) : HelmTheme.ocean,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                // User text is shown verbatim (never rendered as markdown).
                Text(entry.content, style: TextStyle(color: entry.failed ? HelmTheme.error : Colors.white)),
                if (entry.failed)
                  const Text('Not sent', style: TextStyle(color: HelmTheme.error, fontSize: 12)),
              ],
            ),
          ),
        ),
      );
    }
    final turn = entry.turn!;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.black12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AssistantAnswer(turn: turn),
          const SizedBox(height: 6),
          Text(DateFormat('d MMM, h:mm a').format(turn.createdAt.toLocal()),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: HelmTheme.mutedText)),
        ],
      ),
    );
  }
}

class _ThinkingBubble extends StatelessWidget {
  const _ThinkingBubble();

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      label: 'First Mate is checking the sources',
      child: const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 10),
            Text('Checking the sources…'),
          ],
        ),
      ),
    );
  }
}

class _ChatErrorBanner extends StatelessWidget {
  const _ChatErrorBanner({required this.error, required this.canRetry, required this.onRetry, required this.onDismiss});

  final Object error;
  final bool canRetry;
  final VoidCallback onRetry;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final api = ApiError.from(error);
    final (String title, String message) = switch (api) {
      ApiError(statusCode: 429) => (
          'Slow down a little',
          'You have sent a lot of messages. Please wait a minute before asking again. (${api.detail})',
        ),
      ApiError(code: 'ai_unavailable') => (
          'First Mate is unavailable',
          '${api.detail}. Your message was not answered; try again later.',
        ),
      ApiError(code: 'rate_limit_unavailable') => ('First Mate is unavailable', api.detail),
      _ => ('Message not answered', describeError(error)),
    };
    return Semantics(
      liveRegion: true,
      child: Material(
        color: HelmTheme.error.withValues(alpha: 0.08),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(
            children: [
              const Icon(Icons.error_outline, color: HelmTheme.error),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
                    Text(message),
                    if (api != null) Text('Code: ${api.code}', style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
              if (canRetry && api?.statusCode != 429) TextButton(onPressed: onRetry, child: const Text('Retry')),
              IconButton(onPressed: onDismiss, icon: const Icon(Icons.close), tooltip: 'Dismiss'),
            ],
          ),
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.focusNode, required this.sending, required this.onSend});

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final length = controller.text.trim().length;
    final tooLong = controller.text.length > maxChatMessageChars;
    final canSend = !sending && length > 0 && !tooLong;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: ContentWidth(
          maxWidth: 860,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: CallbackShortcuts(
                  bindings: {
                    const SingleActivator(LogicalKeyboardKey.enter): () {
                      if (canSend) onSend();
                    },
                  },
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    minLines: 1,
                    maxLines: 5,
                    maxLength: maxChatMessageChars,
                    maxLengthEnforcement: MaxLengthEnforcement.enforced,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) {
                      if (canSend) onSend();
                    },
                    decoration: InputDecoration(
                      labelText: 'Ask your First Mate',
                      hintText: 'e.g. Which spark plug does my engine need?',
                      helperText: 'Up to $maxChatMessageChars characters',
                      counterText: '${controller.text.length} / $maxChatMessageChars',
                      errorText: tooLong ? 'Message is limited to $maxChatMessageChars characters' : null,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: IconButton.filled(
                  onPressed: canSend ? onSend : null,
                  icon: sending
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.send),
                  tooltip: 'Send',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ConversationDrawer extends ConsumerWidget {
  const _ConversationDrawer({required this.vesselKey});

  final String? vesselKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conversations = ref.watch(conversationListProvider);
    final current = ref.watch(chatProvider(vesselKey).select((s) => s.conversationId));
    final vessels = ref.watch(vesselListProvider).value ?? const <Vessel>[];
    String? vesselName(String? id) {
      for (final v in vessels) {
        if (v.id == id) return v.nickname;
      }
      return null;
    }

    return Drawer(
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 8, 8),
              child: Row(
                children: [
                  Expanded(
                    child: Semantics(
                      header: true,
                      child: Text('Conversations', style: Theme.of(context).textTheme.titleMedium),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    tooltip: 'Refresh conversations',
                    onPressed: () => ref.invalidate(conversationListProvider),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: conversations.when(
                loading: () => const LoadingView(message: 'Loading conversations'),
                error: (e, _) => ErrorView(
                  error: e,
                  title: 'Could not load conversations',
                  onRetry: () => ref.invalidate(conversationListProvider),
                ),
                data: (list) => list.isEmpty
                    ? const Center(child: Padding(padding: EdgeInsets.all(24), child: Text('No conversations yet.')))
                    : ListView(
                        children: [
                          for (final c in list)
                            _ConversationTile(
                              summary: c,
                              selected: c.id == current,
                              vesselName: vesselName(c.vesselId),
                              vesselKey: vesselKey,
                            ),
                        ],
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ConversationTile extends ConsumerWidget {
  const _ConversationTile({
    required this.summary,
    required this.selected,
    required this.vesselName,
    required this.vesselKey,
  });

  final ConversationSummary summary;
  final bool selected;
  final String? vesselName;
  final String? vesselKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final when = DateFormat('d MMM, h:mm a').format(summary.updatedAt.toLocal());
    return ListTile(
      selected: selected,
      title: Text(summary.displayTitle, maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Text([when, '${summary.messageCount} messages', ?vesselName].join(' · ')),
      onTap: () {
        Navigator.of(context).pop();
        ref.read(chatProvider(vesselKey).notifier).open(summary.id);
      },
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline),
        tooltip: 'Delete conversation',
        onPressed: () async {
          final ok = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Delete conversation?'),
              content: Text('“${summary.displayTitle}” will be permanently deleted.'),
              actions: [
                TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
                FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Delete')),
              ],
            ),
          );
          if (ok != true || !context.mounted) return;
          try {
            await ref.read(chatProvider(vesselKey).notifier).delete(summary.id);
          } catch (e) {
            if (context.mounted) showErrorSnackBar(context, e, prefix: 'Could not delete');
          }
        },
      ),
    );
  }
}
