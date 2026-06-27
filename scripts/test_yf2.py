import yfinance as yf
print(yf.download('^GSPC', period='7d', interval='1d'))
