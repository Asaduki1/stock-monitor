import json
import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime

# ===== 設定 =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ===== Telegram通知 =====
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

# ===== 株価・指標取得 =====
def get_stock_data(code):
    ticker = yf.Ticker(f"{code}.T")
    hist = ticker.history(period="3mo")
    if hist.empty:
        return None
    
    price = round(hist["Close"].iloc[-1], 1)
    
    # 移動平均（25日）
    ma25 = round(hist["Close"].rolling(25).mean().iloc[-1], 1)
    
    # 乖離率
    divergence = round((price - ma25) / ma25 * 100, 2)
    
    # RSI（14日）
    delta = hist["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1)
    
    return price, ma25, divergence, rsi

# ===== メイン処理 =====
def main():
    with open("data/master.json", "r", encoding="utf-8") as f:
        stocks = json.load(f)

    results = []
    new_buys = []

    for stock in stocks:
        code = stock["code"]
        name = stock["name"]
        dividend = stock["dividend"]
        avg_yield = stock["avg_yield"]

        data = get_stock_data(code)
        if data is None:
            continue

        price, ma25, divergence, rsi = data

        # 配当利回り
        yield_rate = round(dividend / price * 100, 2)

        # シグナル判定
        signal = "WAIT"
        if divergence <= -10 and rsi <= 35 and yield_rate >= avg_yield + 0.7:
            signal = "BUY"

        result = {
            "code": code,
            "name": name,
            "price": price,
            "ma25": ma25,
            "divergence": divergence,
            "rsi": rsi,
            "yield": yield_rate,
            "signal": signal,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        results.append(result)

        if signal == "BUY":
            new_buys.append(f"🟢 {name}({code})\n株価:{price}円 RSI:{rsi} 乖離率:{divergence}% 利回り:{yield_rate}%")

    # result.json保存
    with open("data/result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Telegram通知
    if new_buys:
        message = "【BUYシグナル検出】\n\n" + "\n\n".join(new_buys)
        send_telegram(message)

if __name__ == "__main__":
    main()
