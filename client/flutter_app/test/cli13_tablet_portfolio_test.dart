import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/domain/entities/candle.dart';
import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/application/kline/history_kline_service.dart';

// ─── Test Doubles ─────────────────────────────────────────────────────────────

class FakeRestGateway implements QuantRestGateway {
  FakeRestGateway({this.getResponse});

  final ApiResult<Object?>? getResponse;
  String? lastGetPath;
  Map<String, dynamic>? lastQuery;

  @override
  Future<ApiResult<T>> get<T>(
    String path, {
    Map<String, dynamic>? query,
    T Function(Object? json)? parse,
  }) async {
    lastGetPath = path;
    lastQuery = query;
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
    throw UnimplementedError();
  }
}

// ─── CandleBar.fromJson ──────────────────────────────────────────────────────

void main() {
  group('CandleBar.fromJson', () {
    test('parses standard backend format', () {
      final json = {
        'time': '2024-06-01T00:00:00',
        'open': 100.5,
        'high': 105.2,
        'low': 99.1,
        'close': 103.8,
        'volume': 1234567,
      };
      final bar = CandleBar.fromJson(json);
      expect(bar.time, DateTime.parse('2024-06-01T00:00:00'));
      expect(bar.open, 100.5);
      expect(bar.high, 105.2);
      expect(bar.low, 99.1);
      expect(bar.close, 103.8);
      expect(bar.volume, 1234567.0);
    });

    test('parses numeric timestamp', () {
      final ts = DateTime(2024, 1, 15).millisecondsSinceEpoch;
      final json = {
        'time': ts,
        'open': 50,
        'high': 55,
        'low': 48,
        'close': 52,
      };
      final bar = CandleBar.fromJson(json);
      expect(bar.time, DateTime.fromMillisecondsSinceEpoch(ts));
      expect(bar.volume, isNull);
    });

    test('parses string numbers', () {
      final json = {
        'time': '2024-03-01',
        'open': '100.5',
        'high': '105.2',
        'low': '99.1',
        'close': '103.8',
        'volume': '5000',
      };
      final bar = CandleBar.fromJson(json);
      expect(bar.open, 100.5);
      expect(bar.close, 103.8);
      expect(bar.volume, 5000.0);
    });

    test('handles missing fields gracefully', () {
      final json = {'time': '2024-01-01'};
      final bar = CandleBar.fromJson(json);
      expect(bar.open, 0);
      expect(bar.high, 0);
      expect(bar.low, 0);
      expect(bar.close, 0);
      expect(bar.volume, isNull);
    });

    test('isBull returns true when close >= open', () {
      final bull = CandleBar.fromJson({
        'time': '2024-01-01',
        'open': 100.0,
        'high': 110.0,
        'low': 95.0,
        'close': 105.0,
      });
      expect(bull.isBull, isTrue);

      final bear = CandleBar.fromJson({
        'time': '2024-01-01',
        'open': 100.0,
        'high': 110.0,
        'low': 95.0,
        'close': 95.0,
      });
      expect(bear.isBull, isFalse);
    });
  });

  // ─── HistoryKlineService ────────────────────────────────────────────────────

  group('HistoryKlineService', () {
    test('fetchHistory sends correct path and query', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.success([
          {'time': '2024-01-01', 'open': 100, 'high': 105, 'low': 99, 'close': 103},
        ]),
      );
      final service = HistoryKlineService(gateway: gw);

      await service.fetchHistory(ticker: 'HK.00700', ktype: 'K_DAY', num: 60);

      expect(gw.lastGetPath, '/api/v1/market/history');
      expect(gw.lastQuery, {'ticker': 'HK.00700', 'ktype': 'K_DAY', 'num': 60});
    });

    test('fetchHistory parses bars from response', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.success([
          {'time': '2024-01-01', 'open': 100, 'high': 105, 'low': 99, 'close': 103, 'volume': 1000},
          {'time': '2024-01-02', 'open': 103, 'high': 108, 'low': 101, 'close': 106, 'volume': 1200},
        ]),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isTrue);
      expect(result.data, hasLength(2));
      expect(result.data![0].close, 103);
      expect(result.data![1].close, 106);
    });

    test('fetchHistory returns failure on gateway error', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.failure(message: 'Network error'),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isFalse);
      expect(result.message, contains('Network error'));
    });
  });

  // ─── HistoryKlineState ──────────────────────────────────────────────────────

  group('HistoryKlineState', () {
    test('isEmpty returns true when bars is empty', () {
      const state = HistoryKlineState();
      expect(state.isEmpty, isTrue);
      expect(state.isLoading, isFalse);
      expect(state.error, isNull);
    });

    test('isEmpty returns false when bars is non-empty', () {
      final state = HistoryKlineState(
        bars: [
          CandleBar(
            time: DateTime(2024, 1, 1),
            open: 100,
            high: 105,
            low: 99,
            close: 103,
          ),
        ],
      );
      expect(state.isEmpty, isFalse);
    });

    test('copyWith preserves fields correctly', () {
      const initial = HistoryKlineState(isLoading: true);
      final updated = initial.copyWith(
        isLoading: false,
        bars: [
          CandleBar(
            time: DateTime(2024, 1, 1),
            open: 100,
            high: 105,
            low: 99,
            close: 103,
          ),
        ],
      );
      expect(updated.isLoading, isFalse);
      expect(updated.bars, hasLength(1));
      expect(updated.error, isNull);
    });

    test('copyWith clearError removes error', () {
      const state = HistoryKlineState(error: 'some error');
      final cleared = state.copyWith(clearError: true);
      expect(cleared.error, isNull);
    });
  });
}
