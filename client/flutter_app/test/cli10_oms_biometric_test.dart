import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/domain/entities/order.dart';
import 'package:flutter_app/domain/ports/biometric_auth.dart';
import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/application/oms/oms_service.dart';
import 'package:flutter_app/application/oms/kill_switch_service.dart';
import 'package:flutter_app/injection.dart';

// ─── Test Doubles ─────────────────────────────────────────────────────────────

/// Fake REST gateway that returns configurable responses.
class FakeRestGateway implements QuantRestGateway {
  FakeRestGateway({this.getResponse, this.postResponse});

  final ApiResult<Object?>? getResponse;
  final ApiResult<Object?>? postResponse;

  String? lastGetPath;
  String? lastPostPath;
  Object? lastPostBody;

  @override
  Future<ApiResult<T>> get<T>(
    String path, {
    Map<String, dynamic>? query,
    T Function(Object? json)? parse,
  }) async {
    lastGetPath = path;
    final resp = getResponse;
    if (resp != null && !resp.ok) {
      return ApiResult.failure(message: resp.message!);
    }
    if (parse != null) {
      return ApiResult.success(parse(resp?.data));
    }
    return ApiResult.success(resp?.data as T);
  }

  @override
  Future<ApiResult<T>> post<T>(
    String path, {
    Object? body,
    T Function(Object? json)? parse,
  }) async {
    lastPostPath = path;
    lastPostBody = body;
    final resp = postResponse ?? getResponse;
    if (resp != null && !resp.ok) {
      return ApiResult.failure(message: resp.message!);
    }
    if (parse != null) {
      return ApiResult.success(parse(resp?.data));
    }
    return ApiResult.success(null as T);
  }
}

/// Fake biometric auth for testing the gate logic.
class FakeBiometricAuth implements BiometricAuth {
  FakeBiometricAuth({this.available = true, this.authResult = true});

  final bool available;
  final bool authResult;
  int authenticateCallCount = 0;

  @override
  Future<bool> isAvailable() async => available;

  @override
  Future<bool> authenticate({required String reason}) async {
    authenticateCallCount++;
    return authResult;
  }
}

void main() {
  // ─── Order entity ──────────────────────────────────────────────────────────

  group('Order', () {
    test('fromJson parses snake_case backend format', () {
      final json = {
        'order_id': 'ord_001',
        'symbol': '00700.HK',
        'side': 'BUY',
        'quantity': 200,
        'price': 368.4,
        'status': 'PENDING',
        'market': 'HK',
        'created_at': 1720000000000,
        'filled_quantity': 0,
        'avg_filled_price': 0,
      };

      final order = Order.fromJson(json);
      expect(order.orderId, 'ord_001');
      expect(order.symbol, '00700.HK');
      expect(order.side, 'BUY');
      expect(order.quantity, 200);
      expect(order.price, 368.4);
      expect(order.status, 'PENDING');
      expect(order.market, 'HK');
      expect(order.isCancellable, isTrue);
      expect(order.orderValue, 73680.0);
    });

    test('fromJson parses camelCase alias format', () {
      final json = {
        'id': 'ord_002',
        'ticker': 'AAPL',
        'direction': 'sell',
        'qty': 10,
        'price': 214.0,
        'status': 'partial',
        'filledQty': 5,
        'avgFilledPrice': 213.5,
      };

      final order = Order.fromJson(json);
      expect(order.orderId, 'ord_002');
      expect(order.symbol, 'AAPL');
      expect(order.side, 'SELL');
      expect(order.quantity, 10);
      expect(order.status, 'PARTIAL');
      expect(order.isCancellable, isTrue);
      expect(order.filledQuantity, 5);
    });

    test('isCancellable is false for FILLED and CANCELLED', () {
      final filled = Order.fromJson({
        'order_id': 'ord_003',
        'symbol': 'TSLA',
        'side': 'BUY',
        'quantity': 5,
        'price': 248.0,
        'status': 'FILLED',
      });
      expect(filled.isCancellable, isFalse);

      final cancelled = Order.fromJson({
        'order_id': 'ord_004',
        'symbol': 'TSLA',
        'side': 'SELL',
        'quantity': 5,
        'price': 260.0,
        'status': 'CANCELLED',
      });
      expect(cancelled.isCancellable, isFalse);
    });

    test('fromJson handles empty fields gracefully', () {
      final order = Order.fromJson({});
      expect(order.orderId, '');
      expect(order.symbol, '');
      expect(order.quantity, 0);
      expect(order.price, 0);
      expect(order.orderValue, 0);
    });

    test('equatable props work', () {
      const a = Order(
        orderId: '1',
        symbol: 'AAPL',
        side: 'BUY',
        quantity: 10,
        price: 214,
        status: 'PENDING',
      );
      const b = Order(
        orderId: '1',
        symbol: 'AAPL',
        side: 'BUY',
        quantity: 10,
        price: 214,
        status: 'PENDING',
      );
      expect(a, equals(b));
    });
  });

  // ─── OmsService ────────────────────────────────────────────────────────────

  group('OmsService', () {
    test('fetchActiveOrders parses active_orders from oms/state', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.success({
          'active_orders': [
            {
              'order_id': 'ord_001',
              'symbol': '00700.HK',
              'side': 'BUY',
              'quantity': 200,
              'price': 368.4,
              'status': 'PENDING',
            },
            {
              'order_id': 'ord_002',
              'symbol': 'AAPL',
              'side': 'SELL',
              'quantity': 10,
              'price': 214.0,
              'status': 'PARTIAL',
            },
          ],
        }),
      );
      final service = OmsService(gateway: gw);

      final result = await service.fetchActiveOrders();
      expect(result.ok, isTrue);
      expect(result.data, hasLength(2));
      expect(result.data![0].orderId, 'ord_001');
      expect(result.data![1].status, 'PARTIAL');
    });

    test('fetchActiveOrders returns empty list when no active orders', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.success({'active_orders': []}),
      );
      final service = OmsService(gateway: gw);

      final result = await service.fetchActiveOrders();
      expect(result.ok, isTrue);
      expect(result.data, isEmpty);
    });

    test('fetchActiveOrders returns failure on API error', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.failure(message: 'Network error'),
      );
      final service = OmsService(gateway: gw);

      final result = await service.fetchActiveOrders();
      expect(result.ok, isFalse);
      expect(result.message, contains('Network'));
    });

    test('cancelOrder sends correct path and idempotency key', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.success({'status': 'ok'}),
      );
      final service = OmsService(gateway: gw);

      final result = await service.cancelOrder('ord_001');
      expect(result.ok, isTrue);
      expect(gw.lastPostPath, '/api/v1/oms/orders/ord_001/cancel');
      expect(gw.lastPostBody, isA<Map>());
      expect((gw.lastPostBody as Map).containsKey('idempotency_key'), isTrue);
    });

    test('placeOrder sends correct body', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.success({'order_id': 'ord_new'}),
      );
      final service = OmsService(gateway: gw);

      final result = await service.placeOrder(
        ticker: 'HK.00700',
        qty: 200,
        price: 368.4,
        action: 'BUY',
        market: 'HK',
      );
      expect(result.ok, isTrue);
      expect(gw.lastPostPath, '/api/v1/trade/order');
      final body = gw.lastPostBody as Map;
      expect(body['ticker'], 'HK.00700');
      expect(body['qty'], 200);
      expect(body['action'], 'BUY');
    });
  });

  // ─── BiometricAuth gate logic ──────────────────────────────────────────────

  group('BiometricAuth', () {
    test('FakeBiometricAuth reports availability', () async {
      final auth = FakeBiometricAuth(available: true);
      expect(await auth.isAvailable(), isTrue);

      final noAuth = FakeBiometricAuth(available: false);
      expect(await noAuth.isAvailable(), isFalse);
    });

    test('FakeBiometricAuth returns authenticate result', () async {
      final auth = FakeBiometricAuth(authResult: true);
      expect(await auth.authenticate(reason: 'test'), isTrue);
      expect(auth.authenticateCallCount, 1);

      final failAuth = FakeBiometricAuth(authResult: false);
      expect(await failAuth.authenticate(reason: 'test'), isFalse);
      expect(failAuth.authenticateCallCount, 1);
    });
  });

  // ─── KillSwitchService ─────────────────────────────────────────────────────

  group('KillSwitchService', () {
    test('engage sends POST to kill_switch endpoint', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.success({'status': 'engaged'}),
      );
      final service = KillSwitchService(gateway: gw);

      final result = await service.engage();
      expect(result.ok, isTrue);
      expect(gw.lastPostPath, '/api/v1/oms/kill_switch');
      expect(gw.lastPostBody, isA<Map>());
      expect((gw.lastPostBody as Map).containsKey('timestamp'), isTrue);
    });

    test('engage returns failure on API error', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.failure(message: 'Server error'),
      );
      final service = KillSwitchService(gateway: gw);

      final result = await service.engage();
      expect(result.ok, isFalse);
      expect(result.message, contains('Server'));
    });
  });

  // ─── KillSwitchState ───────────────────────────────────────────────────────

  group('KillSwitchState', () {
    test('default state is idle', () {
      const state = KillSwitchState();
      expect(state.isIdle, isTrue);
      expect(state.isEngaging, isFalse);
    });

    test('copyWith updates status', () {
      const state = KillSwitchState();
      final engaging = state.copyWith(
        status: KillSwitchStatus.engaging,
      );
      expect(engaging.isEngaging, isTrue);
      expect(engaging.isIdle, isFalse);
    });
  });
}
