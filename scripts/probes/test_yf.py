import yfinance as yf
print(yf.download('SPY', period='7d', interval='1d'))
