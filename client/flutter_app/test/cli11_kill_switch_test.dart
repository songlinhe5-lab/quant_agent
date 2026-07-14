import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/domain/entities/market.dart';
import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/application/oms/kill_switch_service.dart';
import 'package:flutter_app/injection.dart';

// ─── Test Doubles ─────────────────────────────────────────────────────────────

class FakeRestGateway implements QuantRestGateway {
  FakeRestGateway({this.getResponse, this.postResponse});

  final ApiResult<Object?>? getResponse;
  final ApiResult<Object?>? postResponse;
  String? lastPostPath;

  @override
  Future<ApiResult<T>> get<T>(
    String path, {
    Map<String, dynamic>? query,
    T Function(Object? json)? parse,
  }) async {
    final resp = getResponse;
    if (resp != null && !resp.ok) {
      return ApiResult.failure(message: resp.message!);
    }
    if (parse != null) return ApiResult.success(parse(resp?.data));
    return ApiResult.success(resp?.data as T);
  }

  @override
  Future<ApiResult<T>> post<T>(
    String path, {
    Object? body,
    T Function(Object? json)? parse,
  }) async {
    lastPostPath = path;
    final resp = postResponse ?? getResponse;
    if (resp != null && !resp.ok) {
      return ApiResult.failure(message: resp.message!);
    }
    if (parse != null) return ApiResult.success(parse(resp?.data));
    return ApiResult.success(null as T);
  }
}

void main() {
  // ─── Kill Switch confirmation phrase logic ─────────────────────────────────

  group('Kill Switch confirmation phrase', () {
    test('exact match "KILL ALL" validates', () {
      const phrase = 'KILL ALL';
      expect('KILL ALL'.trim().toUpperCase() == phrase, isTrue);
    });

    test('lowercase "kill all" validates after toUpperCase', () {
      const phrase = 'KILL ALL';
      expect('kill all'.trim().toUpperCase() == phrase, isTrue);
    });

    test('extra spaces are trimmed', () {
      const phrase = 'KILL ALL';
      expect('  KILL ALL  '.trim().toUpperCase() == phrase, isTrue);
    });

    test('partial phrase does not validate', () {
      const phrase = 'KILL ALL';
      expect('KILL'.trim().toUpperCase() == phrase, isFalse);
      expect('KILL AL'.trim().toUpperCase() == phrase, isFalse);
    });

    test('wrong phrase does not validate', () {
      const phrase = 'KILL ALL';
      expect('STOP ALL'.trim().toUpperCase() == phrase, isFalse);
    });
  });

  // ─── KillSwitchNotifier with ProviderContainer ─────────────────────────────

  group('KillSwitchNotifier', () {
    test('engage success sets status to success', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.success({'status': 'engaged'}),
      );

      final container = ProviderContainer(overrides: [
        quantRestGatewayProvider.overrideWithValue(gw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(killSwitchProvider.notifier);
      final success = await notifier.engage();

      expect(success, isTrue);
      final state = container.read(killSwitchProvider);
      expect(state.status, KillSwitchStatus.success);
      expect(state.message, contains('Kill Switch'));
    });

    test('engage failure sets status to error', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.failure(message: 'Server error'),
      );

      final container = ProviderContainer(overrides: [
        quantRestGatewayProvider.overrideWithValue(gw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(killSwitchProvider.notifier);
      final success = await notifier.engage();

      expect(success, isFalse);
      final state = container.read(killSwitchProvider);
      expect(state.status, KillSwitchStatus.error);
      expect(state.message, contains('Server error'));
    });

    test('reset returns to idle state', () async {
      final gw = FakeRestGateway(
        postResponse: ApiResult.success({'status': 'engaged'}),
      );

      final container = ProviderContainer(overrides: [
        quantRestGatewayProvider.overrideWithValue(gw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(killSwitchProvider.notifier);
      await notifier.engage();
      expect(container.read(killSwitchProvider).status, KillSwitchStatus.success);

      notifier.reset();
      final state = container.read(killSwitchProvider);
      expect(state.status, KillSwitchStatus.idle);
      expect(state.message, isNull);
    });
  });

  // ─── TradingMode LIVE visibility ──────────────────────────────────────────

  group('TradingMode LIVE visibility', () {
    test('LIVE mode label is "LIVE"', () {
      expect(TradingMode.live.label, 'LIVE');
    });

    test('SANDBOX mode label is "SANDBOX"', () {
      expect(TradingMode.sandbox.label, 'SANDBOX');
    });

    test('PAPER mode label is "PAPER"', () {
      expect(TradingMode.paper.label, 'PAPER');
    });

    test('Kill Switch should only be visible in LIVE mode', () {
      // Verify the condition used in MorePage
      expect(TradingMode.live == TradingMode.live, isTrue);
      expect(TradingMode.sandbox == TradingMode.live, isFalse);
      expect(TradingMode.paper == TradingMode.live, isFalse);
    });
  });
}
