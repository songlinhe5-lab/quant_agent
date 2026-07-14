import 'dart:convert';
import 'dart:io';
import 'dart:ui' show Color;

import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/presentation/theme/color_tokens.dart';

void main() {
  late Map<String, dynamic> sync;

  setUpAll(() {
    final file = File('design/figma_variables_sync.json');
    expect(file.existsSync(), isTrue, reason: 'run from client/flutter_app');
    sync = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  });

  test('CLI-ARCH-02: color tokens match Figma sync JSON', () {
    final tokens = (sync['tokens'] as List).cast<Map<String, dynamic>>();
    final byDart = {
      for (final t in tokens) t['dart'] as String: t,
    };

    void expectColor(String dartName, Color actual) {
      final row = byDart[dartName];
      expect(row, isNotNull, reason: 'missing $dartName in sync JSON');
      final hex = (row!['hex'] as String).replaceFirst('#', '');
      final alpha = row['alpha'];
      final expected = _colorFromHex(hex, alpha: alpha is num ? alpha.toDouble() : 1.0);
      expect(
        actual,
        expected,
        reason: '$dartName should be ${row['hex']}'
            '${alpha != null ? ' @ $alpha' : ''}',
      );
    }

    expectColor('AppColors.bull', AppColors.bull);
    expectColor('AppColors.bear', AppColors.bear);
    expectColor('AppColors.warn', AppColors.warn);
    expectColor('AppColors.primary', AppColors.primary);
    expectColor('AppColors.bgPrimary', AppColors.bgPrimary);
    expectColor('AppColors.bgCard', AppColors.bgCard);
    expectColor('AppColors.label', AppColors.label);
    expectColor('AppColors.onSurface', AppColors.onSurface);
    expectColor('AppColors.border', AppColors.border);
  });

  test('CLI-ARCH-02: space / radius match sync JSON', () {
    final space = (sync['space'] as List).cast<Map<String, dynamic>>();
    final radius = (sync['radius'] as List).cast<Map<String, dynamic>>();

    expect(_spaceByDart(space, 'AppSpace.s1'), AppSpace.s1);
    expect(_spaceByDart(space, 'AppSpace.s2'), AppSpace.s2);
    expect(_spaceByDart(space, 'AppSpace.s3'), AppSpace.s3);
    expect(_spaceByDart(space, 'AppSpace.s4'), AppSpace.s4);
    expect(_spaceByDart(space, 'AppSpace.s6'), AppSpace.s6);

    expect(_spaceByDart(radius, 'AppRadius.sm'), AppRadius.sm);
    expect(_spaceByDart(radius, 'AppRadius.md'), AppRadius.md);
    expect(_spaceByDart(radius, 'AppRadius.lg'), AppRadius.lg);
  });
}

double _spaceByDart(List<Map<String, dynamic>> rows, String dart) {
  final row = rows.firstWhere((r) => r['dart'] == dart);
  return (row['px'] as num).toDouble();
}

Color _colorFromHex(String hex, {double alpha = 1.0}) {
  final v = int.parse(hex, radix: 16);
  final a = (alpha.clamp(0.0, 1.0) * 255).round();
  if (hex.length == 6) {
    return Color((a << 24) | v);
  }
  return Color(v);
}
