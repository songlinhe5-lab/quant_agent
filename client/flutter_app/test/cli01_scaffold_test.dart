import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/domain/ports/app_telemetry.dart';
import 'package:flutter_app/domain/ports/auth_token_store.dart';
import 'package:flutter_app/domain/ports/market_stream_gateway.dart';
import 'package:flutter_app/domain/ports/push_notification_port.dart';
import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/injection.dart';
import 'package:flutter_app/main.dart';
import 'package:flutter_app/presentation/app_router.dart';
import 'package:flutter_app/presentation/shell/adaptive_shell.dart';

import 'test_doubles.dart';

void main() {
  test('shellIndexForLocation maps tab roots', () {
    expect(shellIndexForLocation('/portfolio'), 0);
    expect(shellIndexForLocation('/quotes'), 1);
    expect(shellIndexForLocation('/alerts'), 2);
    expect(shellIndexForLocation('/copilot'), 3);
    expect(shellIndexForLocation('/more'), 4);
  });

  test('injection binds Ports to Adapters', () {
    final container = ProviderContainer(
      overrides: [
        appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
      ],
    );
    addTearDown(container.dispose);

    expect(container.read(quantRestGatewayProvider), isA<QuantRestGateway>());
    expect(
      container.read(marketStreamGatewayProvider),
      isA<MarketStreamGateway>(),
    );
    expect(container.read(authTokenStoreProvider), isA<AuthTokenStore>());
    expect(container.read(appTelemetryProvider), isA<AppTelemetry>());
    expect(
      container.read(pushNotificationProvider),
      isA<PushNotificationPort>(),
    );
  });

  testWidgets('MobileShell shows bottom NavigationBar', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
        ],
        child: QuantAgentApp(router: createAppRouter()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.textContaining('SANDBOX'), findsOneWidget);
  });

  testWidgets('TabletShell shows NavigationRail at ≥600', (tester) async {
    tester.view.physicalSize = const Size(800, 1024);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
        ],
        child: QuantAgentApp(router: createAppRouter()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
  });
}
