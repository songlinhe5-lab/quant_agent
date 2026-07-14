import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/application/alerts/alert_nav.dart';
import 'package:flutter_app/application/alerts/alert_overlay.dart';
import 'package:flutter_app/domain/entities/alert_push.dart';
import 'package:flutter_app/domain/ports/push_notification_port.dart';
import 'package:flutter_app/infrastructure/push/hms_push_adapter.dart';
import 'package:flutter_app/infrastructure/push/push_adapters.dart';
import 'package:flutter_app/injection.dart';
import 'package:flutter_app/main.dart';
import 'package:flutter_app/platform/harmonyos/hms_push.dart';
import 'package:flutter_app/presentation/app_router.dart';
import 'package:flutter_app/presentation/widgets/alert_overlay_host.dart';

import 'test_doubles.dart';

AlertPush _push({
  required String id,
  NotificationPriority priority = NotificationPriority.p1,
  String message = 'test',
  String ticker = 'AAPL',
  AlertUiHint hint = const AlertUiHint(),
}) {
  return AlertPush(
    eventId: id,
    priority: priority,
    message: message,
    ticker: ticker,
    uiHint: hint,
  );
}

void main() {
  group('AlertPush.tryParse', () {
    test('parses docs/18 in-app payload', () {
      final p = AlertPush.tryParse({
        'type': 'alert',
        'event_id': 'e1',
        'priority': 'p0',
        'severity': 'critical',
        'message': 'KILL',
        'ticker': 'AAPL',
        'ui_hint': {'mode': 'fullscreen', 'flash': true, 'route': '/market'},
      });
      expect(p, isNotNull);
      expect(p!.priority, NotificationPriority.p0);
      expect(p.uiHint.mode, 'fullscreen');
      expect(p.ackRequired, isTrue);
    });

    test('rejects garbage', () {
      expect(AlertPush.tryParse({'foo': 1}), isNull);
    });
  });

  group('resolveAlertNavigation', () {
    test('maps /market + symbol to quote detail', () {
      final nav = resolveAlertNavigation(
        const AlertUiHint(route: '/market', symbol: '00700.HK'),
      );
      expect(nav.location, '/quotes/00700.HK');
      expect(nav.symbol, '00700.HK');
    });

    test('maps /quotes + ticker fallback', () {
      final nav = resolveAlertNavigation(
        const AlertUiHint(route: '/quotes'),
        ticker: 'AAPL',
      );
      expect(nav.location, '/quotes/AAPL');
    });

    test('defaults to /alerts when no symbol', () {
      final nav = resolveAlertNavigation(const AlertUiHint());
      expect(nav.location, '/alerts');
    });

    test('passes through /portfolio', () {
      final nav = resolveAlertNavigation(
        const AlertUiHint(route: '/portfolio'),
      );
      expect(nav.location, '/portfolio');
    });
  });

  group('AlertOverlayNotifier', () {
    test('p0 queues, p1 toasts, p3 badge only', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final n = container.read(alertOverlayProvider.notifier);

      n.enqueue(_push(id: 'a', priority: NotificationPriority.p0));
      n.enqueue(_push(id: 'b', priority: NotificationPriority.p1));
      n.enqueue(_push(id: 'c', priority: NotificationPriority.p3));

      final s = container.read(alertOverlayProvider);
      expect(s.p0Queue, hasLength(1));
      expect(s.toastStack, hasLength(1));
      expect(s.badgeCount, 3); // p0 + p1 + p3
    });
  });

  group('Push adapters', () {
    test('MemoryPushAdapter emits messages and tokens', () async {
      final mem = MemoryPushAdapter();
      await mem.start();
      expect(mem.isConfigured, isTrue);

      final msgs = <AlertPush>[];
      final sub = mem.messages.listen(msgs.add);
      mem.emitMessage(_push(id: 'm1'));
      await Future<void>.delayed(Duration.zero);
      expect(msgs.single.eventId, 'm1');
      await sub.cancel();
      await mem.dispose();
    });

    test('FCM / APNs shells + HMS channel adapter share Port contract', () async {
      final adapters = <PushNotificationPort>[
        FcmPushAdapter(),
        ApnsPushAdapter(),
        HmsPushAdapter(bridge: FakeHmsPushBridge(available: false)),
      ];
      expect(adapters.map((a) => a.vendor).toList(), [
        PushVendor.fcm,
        PushVendor.apns,
        PushVendor.hms,
      ]);
      for (final a in adapters) {
        expect(a.isConfigured, isFalse);
        await a.start();
        await a.stop();
      }
    });
  });

  testWidgets('P0 overlay + deep link to quote detail', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final mem = MemoryPushAdapter();
    final router = createAppRouter();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
          pushNotificationProvider.overrideWithValue(mem),
        ],
        child: QuantAgentApp(router: router),
      ),
    );
    await tester.pumpAndSettle();

    mem.emitMessage(
      _push(
        id: 'p0-1',
        priority: NotificationPriority.p0,
        message: '止损触发 AAPL',
        hint: const AlertUiHint(
          mode: 'fullscreen',
          flash: true,
          route: '/market',
          symbol: 'AAPL',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(AlertOverlayHost), findsOneWidget);
    expect(find.text('P0 告警'), findsOneWidget);
    expect(find.text('止损触发 AAPL'), findsOneWidget);

    await tester.tap(find.text('查看并确认'));
    await tester.pumpAndSettle();

    expect(router.state.uri.path, '/quotes/AAPL');
    expect(find.text('P0 告警'), findsNothing);
  });
}
