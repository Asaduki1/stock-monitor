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

# ===== 銘柄情報を自動補完 =====
def enrich_stock_info(stock):
    code = stock["code"]
    ticker = yf.Ticker(f"{code}.T")
    info = ticker.info

    # 銘柄名が未設定なら自動取得
    if not stock.get("name"):
        stock["name"] = info.get("longNameJa") or info.get("shortNameJa") or info.get("shortName") or info.get("longName") or code

    # 配当が未設定なら自動取得
    if not stock.get("dividend"):
        div = info.get("dividendRate")
        if div:
            stock["dividend"] = round(float(div), 2)
        else:
            stock["dividend"] = 0

    # 平均利回りが未設定なら配当利回りを参考に設定
    if not stock.get("avg_yield"):
        dy = info.get("dividendYield")
        if dy:
            stock["avg_yield"] = round(float(dy) * 100, 2)
        else:
            stock["avg_yield"] = 3.0

    return stock

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

    # 銘柄情報を補完してmaster.jsonを更新
    updated = False
    for i, stock in enumerate(stocks):
        if not stock.get("name") or not stock.get("dividend") or not stock.get("avg_yield"):
            print(f"{stock['code']} の情報を自動取得中...")
            stocks[i] = enrich_stock_info(stock)
            updated = True

    if updated:
        with open("data/master.json", "w", encoding="utf-8") as f:
            json.dump(stocks, f, ensure_ascii=False, indent=2)
        print("master.json を更新しました")

    results = []
    new_buys = []

    for stock in stocks:
        code = stock["code"]
        name = stock.get("name", code)
        dividend = stock.get("dividend", 0)
        avg_yield = stock.get("avg_yield", 3.0)

        data = get_stock_data(code)
        if data is None:
            print(f"{code} のデータ取得失敗")
            continue

        price, ma25, divergence, rsi = data

        # 配当利回り
        if price > 0 and dividend > 0:
            yield_rate = round(dividend / price * 100, 2)
        else:
            yield_rate = 0.0

        # シグナル判定
        cond_divergence = divergence <= -3
        cond_rsi = rsi <= 50
        cond_yield = yield_rate >= avg_yield + 0.7
        matched = sum([cond_divergence, cond_rsi, cond_yield])

        if matched == 3:
            signal = "BUY"
        elif matched == 2:
            signal = "WATCH"
        else:
            signal = "WAIT"

        result = {
            "code": code,
            "name": name,
            "price": price,
            "ma25": ma25,
            "divergence": divergence,
            "rsi": rsi,
            "yield": yield_rate,
            "dividend": dividend,
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
