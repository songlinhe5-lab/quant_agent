import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/domain/ports/quant_rest_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/infrastructure/telemetry/fps_sampler.dart';
import 'package:flutter_app/infrastructure/telemetry/http_app_telemetry.dart';

class _FakeGateway implements QuantRestGateway {
  final posts = <({String path, Object? body})>[];
  bool fail = false;

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
    posts.add((path: path, body: body));
    if (fail) {
      return ApiResult.failure(message: 'boom', errorCode: 'TEST');
    }
    final data =
        parse == null ? <String, dynamic>{} as T : parse({'received_at': 1});
    return ApiResult.success(data);
  }
}

void main() {
  test('FpsSampler averages injected samples', () {
    final s = FpsSampler(maxSamples: 10);
    s.debugAddSample(60);
    s.debugAddSample(40);
    expect(s.averageFps, closeTo(50, 0.01));
  });

  test('flushHeartbeat posts FPS / memory / wsLatency', () async {
    final gateway = _FakeGateway();
    final fps = FpsSampler();
    fps.debugAddSample(59.7);

    final telemetry = HttpAppTelemetry(
      gateway: gateway,
      appVersion: '0.1.0-test',
      fpsSampler: fps,
      memoryMbReader: () => 128.4,
      platformReader: () => 'android',
      nowMs: () => 1700000000000,
      deviceIdResolver: () async => 'device-test-1',
      initialFlushDelay: Duration.zero,
    );

    telemetry.recordWsLatency(const Duration(milliseconds: 18));
    await telemetry.flushHeartbeat();

    expect(gateway.posts, hasLength(1));
    expect(gateway.posts.single.path, '/api/v1/client/heartbeat');
    final body = gateway.posts.single.body! as Map<String, dynamic>;
    expect(body['platform'], 'android');
    expect(body['appVersion'], '0.1.0-test');
    expect(body['deviceId'], 'device-test-1');
    expect(body['timestamp'], 1700000000000);
    expect(body['fps'], 59.7);
    expect(body['memoryMb'], 128.4);
    expect(body['wsLatencyMs'], 18);
    expect(telemetry.flushCount, 1);
  });

  test('start schedules periodic flush every interval', () async {
    final gateway = _FakeGateway();
    final telemetry = HttpAppTelemetry(
      gateway: gateway,
      appVersion: '0.1.0',
      platformReader: () => 'ios',
      memoryMbReader: () => 64,
      nowMs: () => 42,
      deviceIdResolver: () async => 'dev-2',
      interval: const Duration(milliseconds: 30),
      initialFlushDelay: Duration.zero,
    );

    telemetry.start();
    await Future<void>.delayed(const Duration(milliseconds: 100));
    telemetry.stop();

    expect(gateway.posts.length, greaterThanOrEqualTo(2));
    expect(
      gateway.posts.every((p) => p.path == '/api/v1/client/heartbeat'),
      isTrue,
    );
  });

  test('failed post increments errorCount', () async {
    final gateway = _FakeGateway()..fail = true;
    final telemetry = HttpAppTelemetry(
      gateway: gateway,
      appVersion: '0.1.0',
      platformReader: () => 'android',
      deviceIdResolver: () async => 'dev-3',
      initialFlushDelay: Duration.zero,
    );

    await telemetry.flushHeartbeat();
    expect(telemetry.flushCount, 0);
    expect(telemetry.errorCount, greaterThan(0));
  });
}
