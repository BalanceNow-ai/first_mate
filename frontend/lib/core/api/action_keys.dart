/// One Idempotency-Key per logical user action.
///
/// A retry of the same action (same target and payload) after an error or a lost
/// response reuses its key, so the server replays the first result instead of acting
/// twice; a success discards the key, so the next action gets a fresh one. A
/// different payload is a different action and gets its own key.
class ActionKeys {
  ActionKeys(this._generate);

  final String Function(String tag) _generate;
  final Map<String, String> _keys = {};

  String _id(String tag, String action) => '$tag|$action';

  /// The key for [action] (generated once, reused until the action succeeds).
  String keyFor(String tag, String action) => _keys.putIfAbsent(_id(tag, action), () => _generate(tag));

  /// Sends [action] with its key; the key is discarded only when [send] succeeds.
  Future<T> run<T>(String tag, String action, Future<T> Function(String key) send) async {
    final result = await send(keyFor(tag, action));
    _keys.remove(_id(tag, action));
    return result;
  }
}
