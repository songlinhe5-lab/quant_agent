import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/infrastructure/gateway/auth_bearer_interceptor.dart';
import 'package:flutter_app/infrastructure/gateway/rest_gateway_impl.dart';
import 'package:flutter_app/infrastructure/storage/flutter_secure_kv_store.dart';
import 'package:flutter_app/infrastructure/storage/secure_auth_token_store.dart';
import 'package:flutter_app/injection.dart';

void main() {
  group('SecureAuthTokenStore', () {
    test('save / read / clear round-trip on MemorySecureKvStore', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);

      expect(await store.hasAccessToken(), isFalse);

      await store.saveTokens(access: 'acc-1', refresh: 'ref-1');
      expect(await store.readAccessToken(), 'acc-1');
      expect(await store.readRefreshToken(), 'ref-1');
      expect(await store.hasAccessToken(), isTrue);
      expect(kv.debugData.containsKey(SecureAuthTokenStore.accessKey), isTrue);

      await store.clear();
      expect(await store.readAccessToken(), isNull);
      expect(await store.readRefreshToken(), isNull);
      expect(await store.hasAccessToken(), isFalse);
    });

    test('empty access token is rejected', () async {
      final store = SecureAuthTokenStore(kv: MemorySecureKvStore());
      expect(
        () => store.saveTokens(access: '  ', refresh: 'r'),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('empty refresh deletes refresh key', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);
      await store.saveTokens(access: 'a', refresh: 'r');
      await store.saveTokens(access: 'a2', refresh: '');
      expect(await store.readAccessToken(), 'a2');
      expect(await store.readRefreshToken(), isNull);
    });
  });

  group('AuthBearerInterceptor', () {
    test('attaches Bearer header from store', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);
      await store.saveTokens(access: 'tok-xyz', refresh: 'r');

      final dio = Dio(BaseOptions(baseUrl: 'http://example.test'));
      dio.interceptors.add(AuthBearerInterceptor(store));

      late RequestOptions seen;
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            seen = options;
            handler.resolve(
              Response(requestOptions: options, statusCode: 200, data: {}),
            );
          },
        ),
      );

      await dio.get('/api/v1/oms/positions');
      expect(seen.headers['Authorization'], 'Bearer tok-xyz');
    });

    test('skips bearer on /auth/login', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);
      await store.saveTokens(access: 'tok-xyz', refresh: 'r');

      final dio = Dio(BaseOptions(baseUrl: 'http://example.test'));
      dio.interceptors.add(AuthBearerInterceptor(store));

      late RequestOptions seen;
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            seen = options;
            handler.resolve(
              Response(requestOptions: options, statusCode: 200, data: {}),
            );
          },
        ),
      );

      await dio.post('/api/v1/auth/login');
      expect(seen.headers['Authorization'], isNull);
    });
  });

  group('AuthSessionNotifier', () {
    test('login persists tokens via AuthTokenStore', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);

      final container = ProviderContainer(
        overrides: [
          authTokenStoreProvider.overrideWithValue(store),
          quantRestGatewayProvider.overrideWithValue(
            _FakeLoginGateway(
              response: {
                'status': 'success',
                'access_token': 'jwt-access',
                'refresh_token': 'jwt-refresh',
                'user': {'username': 'trader'},
              },
            ),
          ),
        ],
      );
      addTearDown(container.dispose);

      final ok = await container.read(authSessionProvider.notifier).login(
            username: 'trader',
            password: 'secret',
          );
      expect(ok, isTrue);
      expect(container.read(authSessionProvider).isAuthenticated, isTrue);
      expect(container.read(authSessionProvider).username, 'trader');
      expect(await store.readAccessToken(), 'jwt-access');
      expect(await store.readRefreshToken(), 'jwt-refresh');

      await container.read(authSessionProvider.notifier).logout();
      expect(container.read(authSessionProvider).isAuthenticated, isFalse);
      expect(await store.hasAccessToken(), isFalse);
    });

    test('restore reads existing access token', () async {
      final kv = MemorySecureKvStore();
      final store = SecureAuthTokenStore(kv: kv);
      await store.saveTokens(access: 'cached', refresh: '');

      final container = ProviderContainer(
        overrides: [
          authTokenStoreProvider.overrideWithValue(store),
          quantRestGatewayProvider.overrideWithValue(_FakeLoginGateway()),
        ],
      );
      addTearDown(container.dispose);

      await container.read(authSessionProvider.notifier).restore();
      expect(container.read(authSessionProvider).isAuthenticated, isTrue);
    });
  });

  test('RestGatewayImpl wires AuthBearerInterceptor when tokenStore set', () {
    final store = SecureAuthTokenStore(kv: MemorySecureKvStore());
    final gw = RestGatewayImpl(
      baseUrl: 'http://example.test',
      tokenStore: store,
    );
    expect(
      gw.dio.interceptors.whereType<AuthBearerInterceptor>(),
      isNotEmpty,
    );
  });
}

class _FakeLoginGateway implements QuantRestGateway {
  _FakeLoginGateway({this.response});

  final Map<String, dynamic>? response;

  @override
  Future<ApiResult<T>> get<T>(
    String path, {
    Map<String, dynamic>? query,
    T Function(Object? json)? parse,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<ApiResult<T>> post<T>(
    String path, {
    Object? body,
    T Function(Object? json)? parse,
  }) async {
    if (response == null) {
      return ApiResult.failure(message: 'no response');
    }
    final data = parse == null ? response as T : parse(response);
    return ApiResult.success(data);
  }
}
