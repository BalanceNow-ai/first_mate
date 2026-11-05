import 'package:flutter/material.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';

/// − n + control with accessible labels and 48 dp targets.
class QuantityStepper extends StatelessWidget {
  const QuantityStepper({
    super.key,
    required this.value,
    required this.onChanged,
    this.min = 1,
    this.max = 99,
    this.enabled = true,
    this.itemName,
  });

  final int value;
  final int min;
  final int max;
  final bool enabled;
  final String? itemName;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final suffix = itemName == null ? '' : ' of $itemName';
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: HelmTheme.mutedText.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            icon: const Icon(Icons.remove),
            tooltip: 'Decrease quantity$suffix',
            onPressed: enabled && value > min ? () => onChanged(value - 1) : null,
          ),
          Semantics(
            label: 'Quantity$suffix',
            value: '$value',
            child: ConstrainedBox(
              constraints: const BoxConstraints(minWidth: 32),
              child: Text('$value',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.add),
            tooltip: 'Increase quantity$suffix',
            onPressed: enabled && value < max ? () => onChanged(value + 1) : null,
          ),
        ],
      ),
    );
  }
}
