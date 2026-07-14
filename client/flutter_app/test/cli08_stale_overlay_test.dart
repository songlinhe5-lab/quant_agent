import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/application/session/connection_health.dart';
import 'package:flutter_app/infrastructure/gateway/ws_gateway_impl.dart';
import 'package:flutter_app/injection.dart';
import 'package:flutter_app/main.dart';
import 'package:flutter_app/presentation/app_router.dart';
import 'package:flutter_app/presentation/widgets/stale_overlay.dart';

import 'test_doubles.dart';

void main() {
  group('ConnectionHealth', () {
    test('market / alerts stale flags', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final n = container.read(connectionHealthProvider.notifier);

      expect(container.read(connectionHealthProvider).anyStale, isFalse);
      n.markMarketStale();
      expect(container.read(connectionHealthProvider).marketStale, isTrue);
      n.markAlertsStale();
      expect(container.read(connectionHealthProvider).alertsStale, isTrue);
      n.markAllLive();
      expect(container.read(connectionHealthProvider).anyStale, isFalse);
    });
  });

  group('WsGatewayImpl connection', () {
    test('setMarketConnected emits stream + flips flag', () async {
      final gw = WsGatewayImpl();
      expect(gw.isMarketConnected, isTrue);
      final events = <bool>[];
      final sub = gw.marketConnection.listen(events.add);
      gw.setMarketConnected(false);
      await Future<void>.delayed(Duration.zero);
      expect(gw.isMarketConnected, isFalse);
      expect(events, [false]);
      await sub.cancel();
      await gw.dispose();
    });
  });

  testWidgets('StaleOverlay shows badge only when stale', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: StaleOverlay(
            stale: true,
            label: 'STALE · 行情已断',
            child: Text('price'),
          ),
        ),
      ),
    );
    expect(find.text('STALE · 行情已断'), findsOneWidget);
    expect(find.text('price'), findsOneWidget);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: StaleOverlay(
            stale: false,
            label: 'STALE · 行情已断',
            child: Text('price'),
          ),
        ),
      ),
    );
    expect(find.text('STALE · 行情已断'), findsNothing);
  });

  testWidgets('Quotes page shows STALE when market disconnected', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final gw = WsGatewayImpl();
    final router = createAppRouter(initialLocation: '/quotes');

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
          marketStreamGatewayProvider.overrideWithValue(gw),
        ],
        child: QuantAgentApp(router: router),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('行情'), findsWidgets);
    expect(find.textContaining('STALE'), findsNothing);

    gw.setMarketConnected(false);
    await tester.pumpAndSettle();

    expect(find.textContaining('STALE'), findsWidgets);
  });
}
