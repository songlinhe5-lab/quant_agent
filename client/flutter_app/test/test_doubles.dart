/// Test doubles shared across CLI scaffold tests.
library;

import 'package:flutter_app/domain/ports/app_telemetry.dart';

class NoopAppTelemetry implements AppTelemetry {
  @override
  void recordWsLatency(Duration d) {}

  @override
  void recordError() {}

  @override
  void start() {}

  @override
  void stop() {}

  @override
  Future<void> flushHeartbeat() async {}
}

AppTelemetry createNoopTelemetry() => NoopAppTelemetry();
