export const INDICATOR_WORKER_CODE = `
function calculateMA(dayCount, data) {
  const result = []
  let sum = 0
  for (let i = 0, len = data.length; i < len; i++) {
    sum += data[i].close
    if (i < dayCount - 1) { 
      result.push('-')
    } else {
      result.push(sum / dayCount)
      sum -= data[i - dayCount + 1].close
    }
  }
  return result
}

function calculateMACD(data, short = 12, long = 26, mid = 9) {
  const macd = [], diff = [], dea = []
  let emaShort = data.length ? data[0].close : 0
  let emaLong = data.length ? data[0].close : 0
  let deaVal = 0
  for (let i = 0; i < data.length; i++) {
    const c = data[i].close
    emaShort = (2 * c + (short - 1) * emaShort) / (short + 1)
    emaLong = (2 * c + (long - 1) * emaLong) / (long + 1)
    const d = emaShort - emaLong
    deaVal = (2 * d + (mid - 1) * deaVal) / (mid + 1)
    const m = (d - deaVal) * 2
    diff.push(d); dea.push(deaVal); macd.push(m)
  }
  return { diff, dea, macd }
}

function calculateBollingerBands(data, period = 20, multiplier = 2) {
  const upper = [], lower = [], mid = []
  let sum = 0
  for (let i = 0, len = data.length; i < len; i++) {
    sum += data[i].close
    if (i < period - 1) { 
      upper.push('-'); lower.push('-'); mid.push('-')
    } else {
      const sma = sum / period
      mid.push(sma)
  
      let varianceSum = 0
      for (let j = 0; j < period; j++) varianceSum += Math.pow(data[i - j].close - sma, 2)
      const stdDev = Math.sqrt(varianceSum / period)
  
      upper.push(sma + multiplier * stdDev)
      lower.push(sma - multiplier * stdDev)
      
      sum -= data[i - period + 1].close
    }
  }
  return { upper, lower, mid }
}

function calculateRSI(data, period = 14) {
  const rsi = []
  let avgGain = 0, avgLoss = 0
  for (let i = 0; i < data.length; i++) {
    if (i === 0) { rsi.push('-'); continue }
    const change = data[i].close - data[i - 1].close
    const gain = change > 0 ? change : 0
    const loss = change < 0 ? -change : 0
    if (i < period) {
      avgGain += gain; avgLoss += loss
      rsi.push('-')
    } else if (i === period) {
      avgGain /= period; avgLoss /= period
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
      rsi.push(100 - (100 / (1 + rs)))
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period
      avgLoss = (avgLoss * (period - 1) + loss) / period
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
      rsi.push(100 - (100 / (1 + rs)))
    }
  }
  return rsi
}

function calculateKDJ(data, n = 9, m1 = 3, m2 = 3) {
  const k = [], d = [], j = [];
  let prevK = 50, prevD = 50;
  for (let i = 0; i < data.length; i++) {
    if (i < n - 1) { k.push('-'); d.push('-'); j.push('-'); continue; }
    let minL = data[i].low, maxH = data[i].high;
    for (let step = 1; step < n; step++) {
      if (data[i - step].high > maxH) maxH = data[i - step].high;
      if (data[i - step].low < minL) minL = data[i - step].low;
    }
    let rsv = 50;
    if (maxH !== minL) rsv = ((data[i].close - minL) / (maxH - minL)) * 100;
    const currK = (m1 - 1) / m1 * prevK + (1 / m1) * rsv;
    const currD = (m2 - 1) / m2 * prevD + (1 / m2) * currK;
    const currJ = 3 * currK - 2 * currD;
    k.push(currK); d.push(currD); j.push(currJ);
    prevK = currK; prevD = currD;
  }
  return { k, d, j };
}

// 消息拦截器 (监听主线程派发的任务)
self.onmessage = function(e) {
  const { id, history, params = {} } = e.data;
  const pMA = params.maPeriods || [20, 50, 200];
  const pBB = params.bbParams || [20, 2];
  const pMACD = params.macdParams || [12, 26, 9];
  const pRSI = params.rsiPeriod || 14;
  const pKDJ = params.kdjParams || [9, 3, 3];
  const ma20 = calculateMA(pMA[0], history); const ma50 = calculateMA(pMA[1], history); const ma200 = calculateMA(pMA[2], history); const bb = calculateBollingerBands(history, pBB[0], pBB[1]); const macdCalc = calculateMACD(history, pMACD[0], pMACD[1], pMACD[2]); const rsiCalc = calculateRSI(history, pRSI); const kdjCalc = calculateKDJ(history, pKDJ[0], pKDJ[1], pKDJ[2]);
  self.postMessage({ id, ma20, ma50, ma200, bb, macdCalc, rsiCalc, kdjCalc });
}
`;