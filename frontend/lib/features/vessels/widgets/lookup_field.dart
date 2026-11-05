import 'dart:async';

import 'package:flutter/material.dart';

/// A text field with optional typeahead suggestions from an async source
/// (e.g. the boat database). Suggestions are an assist only: the user may type
/// any value, and a lookup failure simply shows no suggestions.
class LookupField<T extends Object> extends StatefulWidget {
  const LookupField({
    super.key,
    required this.controller,
    required this.label,
    required this.search,
    required this.display,
    this.subtitle,
    this.onSelected,
    this.validator,
    this.hint,
    this.helper,
    this.textCapitalization = TextCapitalization.none,
  });

  final TextEditingController controller;
  final String label;
  final String? hint;
  final String? helper;
  final Future<List<T>> Function(String text) search;
  final String Function(T option) display;
  final String? Function(T option)? subtitle;
  final ValueChanged<T>? onSelected;
  final FormFieldValidator<String>? validator;
  final TextCapitalization textCapitalization;

  @override
  State<LookupField<T>> createState() => _LookupFieldState<T>();
}

class _LookupFieldState<T extends Object> extends State<LookupField<T>> {
  final _focus = FocusNode();
  int _request = 0;

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  Future<Iterable<T>> _options(TextEditingValue value) async {
    final text = value.text.trim();
    final request = ++_request;
    // Light debounce so typing does not fire one request per key.
    await Future<void>.delayed(const Duration(milliseconds: 200));
    if (request != _request || !_focus.hasFocus) return const [];
    try {
      return await widget.search(text);
    } catch (_) {
      return const [];
    }
  }

  @override
  Widget build(BuildContext context) {
    return RawAutocomplete<T>(
      textEditingController: widget.controller,
      focusNode: _focus,
      optionsBuilder: _options,
      displayStringForOption: widget.display,
      onSelected: widget.onSelected,
      fieldViewBuilder: (context, controller, focusNode, onSubmitted) => TextFormField(
        controller: controller,
        focusNode: focusNode,
        decoration: InputDecoration(labelText: widget.label, hintText: widget.hint, helperText: widget.helper),
        textCapitalization: widget.textCapitalization,
        textInputAction: TextInputAction.next,
        validator: widget.validator,
        onFieldSubmitted: (_) => onSubmitted(),
      ),
      optionsViewBuilder: (context, onSelected, options) => Align(
        alignment: Alignment.topLeft,
        child: Material(
          elevation: 4,
          borderRadius: BorderRadius.circular(8),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 280, maxWidth: 480),
            child: ListView(
              padding: EdgeInsets.zero,
              shrinkWrap: true,
              children: [
                for (final o in options)
                  ListTile(
                    title: Text(widget.display(o)),
                    subtitle: widget.subtitle?.call(o) == null ? null : Text(widget.subtitle!(o)!),
                    onTap: () => onSelected(o),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
