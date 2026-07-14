import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/domain/entities/candle.dart';
import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/application/kline/history_kline_service.dart';
import 'package:flutter_app/infrastructure/isolate/isolate_json_parser.dart';

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

// ─── Helper ───────────────────────────────────────────────────────────────────

List<Map<String, dynamic>> _generateBars(int count) {
  return List.generate(count, (i) {
    return {
      'time': '2024-01-${(i % 28 + 1).toString().padLeft(2, '0')}',
      'open': 100.0 + i,
      'high': 105.0 + i,
      'low': 95.0 + i,
      'close': 103.0 + i,
      'volume': 1000 + i * 10,
    };
  });
}

void main() {
  // ─── IsolateJsonParser ────────────────────────────────────────────────────

  group('IsolateJsonParser', () {
    test('decodes small JSON synchronously (below threshold)', () async {
      final parser = IsolateJsonParser();
      final smallJson = jsonEncode({'key': 'value', 'number': 42});
      expect(smallJson.length, lessThan(kIsolateThreshold));

      final result = await parser.decodeLargeJson(smallJson);
      expect(result, isA<Map>());
      expect((result as Map)['key'], 'value');
      expect(result['number'], 42);
    });

    test('decodes large JSON via isolate (above threshold)', () async {
      final parser = IsolateJsonParser();
      // Generate a JSON string > 32KB
      final largeData = {
        'items': List.generate(2000, (i) => {'id': i, 'name': 'item_number_$i', 'value': i * 1.5}),
      };
      final largeJson = jsonEncode(largeData);
      expect(largeJson.length, greaterThan(kIsolateThreshold));

      final result = await parser.decodeLargeJson(largeJson);
      expect(result, isA<Map>());
      final items = (result as Map)['items'] as List;
      expect(items, hasLength(2000));
      expect(items[0]['id'], 0);
      expect(items[1999]['name'], 'item_number_1999');
    });

    test('handles JSON array', () async {
      final parser = IsolateJsonParser();
      final json = jsonEncode([1, 2, 3, 4, 5]);
      final result = await parser.decodeLargeJson(json);
      expect(result, isA<List>());
      expect((result as List), hasLength(5));
    });
  });

  // ─── HistoryKlineService with batch parsing ───────────────────────────────

  group('HistoryKlineService batch parsing', () {
    test('parses small batch directly (< 100 bars)', () async {
      final bars = _generateBars(50);
      final gw = FakeRestGateway(
        getResponse: ApiResult.success(bars),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isTrue);
      expect(result.data, hasLength(50));
      expect(result.data![0].close, 103.0);
      expect(result.data![49].close, 152.0);
    });

    test('parses large batch via compute (> 100 bars)', () async {
      final bars = _generateBars(150);
      final gw = FakeRestGateway(
        getResponse: ApiResult.success(bars),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isTrue);
      expect(result.data, hasLength(150));
      // Verify first and last bars
      expect(result.data!.first.open, 100.0);
      expect(result.data!.last.close, 252.0);
    });

    test('handles empty response', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.success([]),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isTrue);
      expect(result.data, isEmpty);
    });

    test('handles gateway failure', () async {
      final gw = FakeRestGateway(
        getResponse: ApiResult.failure(message: 'Timeout'),
      );
      final service = HistoryKlineService(gateway: gw);
      final result = await service.fetchHistory(ticker: 'HK.00700');

      expect(result.ok, isFalse);
      expect(result.message, contains('Timeout'));
    });
  });

  // ─── CandleBar.fromJson (additional coverage) ─────────────────────────────

  group('CandleBar.fromJson edge cases', () {
    test('handles null volume gracefully', () {
      final json = {
        'time': '2024-01-01',
        'open': 100,
        'high': 105,
        'low': 95,
        'close': 103,
        'volume': null,
      };
      final bar = CandleBar.fromJson(json);
      expect(bar.volume, isNull);
    });

    test('equatable comparison works', () {
      final bar1 = CandleBar.fromJson({
        'time': '2024-01-01',
        'open': 100,
        'high': 105,
        'low': 95,
        'close': 103,
      });
      final bar2 = CandleBar.fromJson({
        'time': '2024-01-01',
        'open': 100,
        'high': 105,
        'low': 95,
        'close': 103,
      });
      expect(bar1, equals(bar2));
    });
  });
}
