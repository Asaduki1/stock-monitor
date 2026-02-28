import json
import requests
import pandas as pd
import os
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("JQUANTS_REFRESH_TOKEN")
API_URL = "https://api.jquants.com"

def get_headers():
    return {"x-api-key": API_KEY}

# ===== 株価取得 =====
def get_prices(code):
    today = datetime.now()
    from_date = (today - timedelta(days=300)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")
    res = requests.get(
        f"{API_URL}/v2/equities/bars/daily",
        headers=get_headers(),
        params={"code": code, "from": from_date, "to": to_date}
    )
    print(f"  株価API: {res.status_code} / {res.text[:200]}")
    data = res.json().get("bars", [])
    if not data:
        return None
    df = pd.DataFrame(data)
    df = df.sort_values("date")
    return df

# ===== 財務情報取得 =====
def get_financials(code):
    res = requests.get(
        f"{API_URL}/v1/fins/statements",
        headers=get_headers(),
        params={"code": code}
    )
    data = res.json().get("statements", [])
    if not data:
        return None
    annual = [d for d in data if d.get("TypeOfDocument") in [
        "FYFinancialStatements_Consolidated_JP",
        "FYFinancialStatements_NonConsolidated_JP",
        "FYFinancialStatements_Consolidated_IFRS",
        "FYFinancialStatements_Consolidated_US"
    ]]
    return annual[-1] if annual else data[-1]

# ===== 銘柄情報取得 =====
def get_stock_info(code):
    res = requests.get(
        f"{API_URL}/v1/listed/info",
        headers=get_headers(),
        params={"code": code}
    )
    data = res.json().get("info", [])
    return data[0] if data else None

# ===== 指標計算 =====
def calc_indicators(df):
    close = df["close"].astype(float)
    price = round(close.iloc[-1], 1)
    ma25 = round(close.rolling(25).mean().iloc[-1], 1) if len(close) >= 25 else None
    divergence = round((price - ma25) / ma25 * 100, 2) if ma25 else None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    rsi = round((100 - (100 / (1 + rs))).iloc[-1], 1) if len(close) >= 14 else None
    return price, ma25, divergence, rsi

# ===== Telegram通知 =====
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message}
    )

# ===== メイン処理 =====
def main():
    print("J-Quants V2 API使用中...")

    with open("data/master.json", "r", encoding="utf-8") as f:
        stocks = json.load(f)

    results = []
    new_buys = []
    new_watches = []

    for stock in stocks:
        code = stock["code"]
        print(f"処理中: {code}")
        try:
            info = get_stock_info(code)
            name = stock.get("name") or (info.get("CompanyName") if info else code)

            df = get_prices(code)
            if df is None or len(df) < 25:
                print(f"  {code}: 株価データ不足")
                continue

            price, ma25, divergence, rsi = calc_indicators(df)

            fins = get_financials(code)
            dividend = stock.get("dividend", 0)
            avg_yield = stock.get("avg_yield", 3.0)

            if fins:
                div_raw = fins.get("AnnualDividendPerShare")
                if div_raw and float(div_raw) > 0:
                    dividend = round(float(div_raw), 2)
                    stock["dividend"] = dividend

            yield_rate = round(dividend / price * 100, 2) if price > 0 and dividend > 0 else 0.0

            cond_divergence = divergence is not None and divergence <= -3
            cond_rsi = rsi is not None and rsi <= 50
            cond_yield = yield_rate >= avg_yield + 0.7
            matched = sum([cond_divergence, cond_rsi, cond_yield])

            if matched == 3:
                signal = "BUY"
            elif matched == 2:
                signal = "WATCH"
            else:
                signal = "WAIT"

            results.append({
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
            })
            print(f"  → 株価{price}円 利回り{yield_rate}% RSI{rsi} 乖離{divergence}% {signal}")

            if signal == "BUY":
                new_buys.append(f"🟢 {name}({code})\n株価:{price}円 RSI:{rsi} 乖離:{divergence}% 利回り:{yield_rate}%")
            elif signal == "WATCH":
                new_watches.append(f"👀 {name}({code})\n株価:{price}円 RSI:{rsi} 乖離:{divergence}% 利回り:{yield_rate}%")

        except Exception as e:
            print(f"  {code} エラー: {e}")
            continue

    with open("data/master.json", "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

    with open("data/result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    if new_buys:
        send_telegram("【🟢 BUYシグナル】\n\n" + "\n\n".join(new_buys))
    if new_watches:
        send_telegram("【👀 WATCHシグナル】\n\n" + "\n\n".join(new_watches))

    print(f"完了: {len(results)}銘柄処理")

if __name__ == "__main__":
    main()
