import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_app/features/quotes/candle_series.dart';
import 'package:flutter_app/presentation/widgets/charts/kline_chart.dart';
import 'package:flutter_app/presentation/widgets/charts/mini_candle_chart.dart';
import 'package:flutter_app/presentation/widgets/charts/sparkline.dart';

void main() {
  test('CandleSeries packs OHLC into Float64List', () {
    final bars = generateDemoCandles(seedSymbol: 'AAPL', count: 20);
    final series = CandleSeries.fromBars(bars);
    expect(series.length, 20);
    expect(series.close.length, 20);
    expect(series.close.last, bars.last.close);
    final range = series.rangeIn(0, 20);
    expect(range.max, greaterThan(range.min));
  });

  test('KlineViewport pan and zoom stay in bounds', () {
    final vp = KlineViewport(seriesLength: 100, start: 40, visibleCount: 40);
    vp.pan(10);
    expect(vp.start, 50);
    vp.pan(100);
    expect(vp.start, 60); // max = 100-40
    vp.zoom(2, anchorFraction: 0.5);
    expect(vp.visibleCount, lessThanOrEqualTo(100));
    expect(vp.visibleCount, greaterThanOrEqualTo(10));
  });

  testWidgets('Sparkline renders for value series', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 200,
            child: Sparkline(values: [1, 2, 1.5, 3, 2.2]),
          ),
        ),
      ),
    );
    expect(find.byType(Sparkline), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('MiniCandleChart and KlineChart paint demo bars', (tester) async {
    final bars = generateDemoCandles(seedSymbol: '00700.HK', count: 80);
    final series = CandleSeries.fromBars(bars);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: Column(
              children: [
                SizedBox(height: 60, child: MiniCandleChart(bars: bars)),
                SizedBox(height: 240, child: KlineChart(series: series, height: 220)),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.byType(MiniCandleChart), findsOneWidget);
    expect(find.byType(KlineChart), findsOneWidget);
    expect(find.byType(RepaintBoundary), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
