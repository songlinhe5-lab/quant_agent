import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/application/session/auth_session.dart';
import 'package:flutter_app/domain/ports/push_notification_port.dart';
import 'package:flutter_app/infrastructure/auth/hms_account_auth_impl.dart';
import 'package:flutter_app/infrastructure/gateway/rest_gateway_impl.dart';
import 'package:flutter_app/infrastructure/push/hms_push_adapter.dart';
import 'package:flutter_app/infrastructure/storage/flutter_secure_kv_store.dart';
import 'package:flutter_app/infrastructure/storage/secure_auth_token_store.dart';
import 'package:flutter_app/infrastructure/telemetry/http_app_telemetry.dart';
import 'package:flutter_app/injection.dart';
import 'package:flutter_app/platform/harmonyos/harmony_os.dart';
import 'package:flutter_app/platform/harmonyos/hms_auth.dart';
import 'package:flutter_app/platform/harmonyos/hms_push.dart';

import 'test_doubles.dart';

void main() {
  group('harmony_os detection', () {
    test('default define is false in unit tests', () {
      expect(kHarmonyOsDefine, isFalse);
      expect(harmonyOsPlatformLabel(), 'harmonyos');
    });

    test('detectClientPlatform is not harmonyos without define', () {
      expect(detectClientPlatform(), isNot(equals('harmonyos')));
    });
  });

  group('HmsPushAdapter', () {
    test('unconfigured when bridge unavailable', () async {
      final bridge = FakeHmsPushBridge(available: false);
      final adapter = HmsPushAdapter(bridge: bridge);
      await adapter.start();
      expect(adapter.vendor, PushVendor.hms);
      expect(adapter.isConfigured, isFalse);
      await adapter.dispose();
    });

    test('emits token + parses push payload when available', () async {
      final bridge = FakeHmsPushBridge(available: true, token: 'tok-hms');
      final adapter = HmsPushAdapter(bridge: bridge);

      final tokens = <String>[];
      final msgs = <String>[];
      final tSub = adapter.tokens.listen(tokens.add);
      final mSub = adapter.messages.listen((p) => msgs.add(p.eventId));

      await adapter.start();
      expect(adapter.isConfigured, isTrue);
      await Future<void>.delayed(Duration.zero);
      expect(tokens, ['tok-hms']);

      bridge.emit({
        'type': 'alert',
        'event_id': 'hms-1',
        'priority': 'p1',
        'message': 'HMS push',
        'ticker': 'AAPL',
        'ui_hint': {'route': '/quotes', 'symbol': 'AAPL'},
      });
      await Future<void>.delayed(Duration.zero);
      expect(msgs, ['hms-1']);

      await tSub.cancel();
      await mSub.cancel();
      await adapter.dispose();
      await bridge.dispose();
    });

    test('consumeInitialMessage parses cold-start payload', () async {
      final bridge = FakeHmsPushBridge(
        available: true,
        initialMessage: {
          'event_id': 'cold-1',
          'priority': 'p0',
          'message': 'KILL',
          'ui_hint': {'mode': 'fullscreen'},
        },
      );
      final adapter = HmsPushAdapter(bridge: bridge);
      await adapter.start();
      final initial = await adapter.consumeInitialMessage();
      expect(initial?.eventId, 'cold-1');
      expect(initial?.priority.name, 'p0');
      await adapter.dispose();
    });
  });

  group('HmsAccountAuth + session', () {
    test('loginWithHms exchanges code for access_token', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);
      final authBridge = FakeHmsAuthBridge();
      final hms = HmsAccountAuthImpl(bridge: authBridge);

      final dio = Dio(BaseOptions(baseUrl: 'http://test'));
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            if (options.path.contains('/auth/hms')) {
              handler.resolve(
                Response(
                  requestOptions: options,
                  statusCode: 200,
                  data: {
                    'status': 'success',
                    'data': {
                      'access_token': 'jwt-hms',
                      'refresh_token': 'ref-hms',
                      'user': {'username': 'hms-user'},
                    },
                  },
                ),
              );
              return;
            }
            handler.reject(
              DioException(requestOptions: options, message: 'unexpected'),
            );
          },
        ),
      );
      final gateway = RestGatewayImpl(baseUrl: 'http://test', dio: dio);

      final container = ProviderContainer(
        overrides: [
          authTokenStoreProvider.overrideWithValue(store),
          quantRestGatewayProvider.overrideWithValue(gateway),
          hmsAccountAuthProvider.overrideWithValue(hms),
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
        ],
      );
      addTearDown(container.dispose);

      final ok =
          await container.read(authSessionProvider.notifier).loginWithHms();
      expect(ok, isTrue);
      expect(authBridge.signInCalls, 1);
      expect(await store.readAccessToken(), 'jwt-hms');
      expect(
        container.read(authSessionProvider).status,
        AuthStatus.authenticated,
      );
    });

    test('loginWithHms fails when HMS unavailable', () async {
      final hms = HmsAccountAuthImpl(
        bridge: FakeHmsAuthBridge(available: false),
      );
      final container = ProviderContainer(
        overrides: [
          authTokenStoreProvider.overrideWithValue(
            SecureAuthTokenStore(kv: MemorySecureKvStore()),
          ),
          hmsAccountAuthProvider.overrideWithValue(hms),
          appTelemetryProvider.overrideWithValue(createNoopTelemetry()),
        ],
      );
      addTearDown(container.dispose);

      final ok =
          await container.read(authSessionProvider.notifier).loginWithHms();
      expect(ok, isFalse);
      expect(
        container.read(authSessionProvider).error,
        contains('HMS Account Kit'),
      );
    });
  });
}
