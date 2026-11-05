import 'package:flutter/material.dart';

/// Helm brand palette (from docs/05_wireframes) and Material 3 themes.
class HelmTheme {
  HelmTheme._();

  static const Color navy = Color(0xFF0A2342);
  static const Color ocean = Color(0xFF1A6B9A);
  static const Color seafoam = Color(0xFF2EC4B6);
  static const Color coral = Color(0xFFE76F51);
  static const Color sand = Color(0xFFF4F1E8);

  static const Color primary = ocean;
  static const Color primaryLight = Color(0xFF4F93C0);
  static const Color primaryDark = navy;
  static const Color secondary = Color(0xFF1F9E93); // seafoam, darkened for contrast
  static const Color accent = coral;
  static const Color surface = Color(0xFFF5F7FA);
  static const Color error = Color(0xFFC53030);
  static const Color success = Color(0xFF2F855A);
  static const Color warning = Color(0xFFB7791F);
  static const Color mutedText = Color(0xFF4A5568);

  /// Darker shade of [color] for text on a tinted background (contrast).
  static Color darken(Color color, [double amount = 0.25]) {
    final hsl = HSLColor.fromColor(color);
    return hsl.withLightness((hsl.lightness - amount).clamp(0.0, 1.0)).toColor();
  }

  /// Minimum interactive size (WCAG / Material guidance).
  static const double minTapTarget = 48;

  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: primary,
          brightness: Brightness.light,
          primary: primary,
          secondary: secondary,
          error: error,
          surface: surface,
        ),
        materialTapTargetSize: MaterialTapTargetSize.padded,
        visualDensity: VisualDensity.standard,
        appBarTheme: const AppBarTheme(
          backgroundColor: navy,
          foregroundColor: Colors.white,
          elevation: 0,
          centerTitle: false,
        ),
        cardTheme: CardThemeData(
          elevation: 1,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          filled: true,
          fillColor: Colors.white,
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: primary,
            foregroundColor: Colors.white,
            minimumSize: const Size(64, minTapTarget),
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(minimumSize: const Size(64, minTapTarget)),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(minimumSize: const Size(48, minTapTarget)),
        ),
        navigationBarTheme: NavigationBarThemeData(
          indicatorColor: primary.withValues(alpha: 0.15),
          labelTextStyle: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.selected)) {
              return const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: navy);
            }
            return const TextStyle(fontSize: 12);
          }),
        ),
      );

  static ThemeData get dark => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: primary, brightness: Brightness.dark),
      );
}
