import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/tooling/layer_boundary.dart';

void main() {
  test('CLI-ARCH-01: lib/ respects Clean Architecture import matrix', () {
    final lib = Directory('lib');
    expect(lib.existsSync(), isTrue, reason: 'run from client/flutter_app');

    final violations = LayerBoundaryChecker(libRoot: lib).check();
    expect(
      violations,
      isEmpty,
      reason: violations.isEmpty
          ? null
          : 'Layer violations:\n${violations.map((v) => ' - $v').join('\n')}',
    );
  });

  test('composition roots are allowlisted for Infrastructure wiring', () {
    expect(
      LayerBoundaryChecker.compositionRoots,
      containsAll(['lib/injection.dart', 'lib/main.dart']),
    );
  });
}
