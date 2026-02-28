import json
import requests
import pandas as pd
import os
from datetime import datetime, timedelta

# ===== 設定 =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
JQUANTS_REFRESH_TOKEN = os.environ.get("JQUANTS_REFRESH_TOKEN")

# ===== J-Quants認証 =====
def get_id_token():
    # APIキー方式
    return JQUANTS_REFRESH_TOKEN

# ===== 株価取得 =====
def get_prices(id_token, code):
    today = datetime.now()
    from_date = (today - timedelta(days=300)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    res = requests.get(
        f"https://api.jquants.com/v1/prices/daily_quotes",
        headers={"Authorization": f"Bearer {id_token}"},
        params={"code": code, "from": from_date, "to": to_date}
    )
    data = res.json().get("daily_quotes", [])
    if not data:
        return None
    df = pd.DataFrame(data)
    df = df[df["AdjustmentClose"].notna()]
    df = df.sort_values("Date")
    return df

# ===== 財務情報取得 =====
def get_financials(id_token, code):
    res = requests.get(
        f"https://api.jquants.com/v1/fins/statements",
        headers={"Authorization": f"Bearer {id_token}"},
        params={"code": code}
    )
    data = res.json().get("statements", [])
    if not data:
        return None
    # 最新の本決算を取得
    annual = [d for d in data if d.get("TypeOfDocument") in [
        "FYFinancialStatements_Consolidated_JP",
        "FYFinancialStatements_NonConsolidated_JP",
        "FYFinancialStatements_Consolidated_IFRS",
        "FYFinancialStatements_Consolidated_US"
    ]]
    if not annual:
        annual = data
    return annual[-1]

# ===== 銘柄情報取得 =====
def get_stock_info(id_token, code):
    res = requests.get(
        f"https://api.jquants.com/v1/listed/info",
        headers={"Authorization": f"Bearer {id_token}"},
        params={"code": code}
    )
    data = res.json().get("info", [])
    if not data:
        return None
    return data[0]

# ===== 指標計算 =====
def calc_indicators(df):
    close = df["AdjustmentClose"].astype(float)
    price = round(close.iloc[-1], 1)

    # 25日移動平均・乖離率
    ma25 = round(close.rolling(25).mean().iloc[-1], 1) if len(close) >= 25 else None
    divergence = round((price - ma25) / ma25 * 100, 2) if ma25 else None

    # RSI（14日）
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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

# ===== メイン処理 =====
def main():
    print("J-Quants認証中...")
    id_token = get_id_token()

    with open("data/master.json", "r", encoding="utf-8") as f:
        stocks = json.load(f)

    results = []
    new_buys = []
    new_watches = []

    for stock in stocks:
        code = stock["code"]
        print(f"処理中: {code}")

        try:
            # 銘柄情報
            info = get_stock_info(id_token, code)
            name = stock.get("name") or (info.get("CompanyName") if info else code)

            # 株価データ
            df = get_prices(id_token, code)
            if df is None or len(df) < 25:
                print(f"  {code}: 株価データ不足")
                continue

            price, ma25, divergence, rsi = calc_indicators(df)

            # 財務データ
            fins = get_financials(id_token, code)
            dividend = stock.get("dividend", 0)
            avg_yield = stock.get("avg_yield", 3.0)

            if fins:
                # J-Quantsから配当取得
                div_raw = fins.get("AnnualDividendPerShare")
                if div_raw and float(div_raw) > 0:
                    dividend = round(float(div_raw), 2)
                    stock["dividend"] = dividend

            # 配当利回り
            yield_rate = round(dividend / price * 100, 2) if price > 0 and dividend > 0 else 0.0

            # シグナル判定
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
            elif signal == "WATCH":
                new_watches.append(f"👀 {name}({code})\n株価:{price}円 RSI:{rsi} 乖離率:{divergence}% 利回り:{yield_rate}%")

        except Exception as e:
            print(f"  {code} エラー: {e}")
            continue

    # master.json更新（配当情報を保存）
    with open("data/master.json", "w", encoding="utf-8") as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)

    # result.json保存
    with open("data/result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Telegram通知
    messages = []
    if new_buys:
        messages.append("【🟢 BUYシグナル】\n\n" + "\n\n".join(new_buys))
    if new_watches:
        messages.append("【👀 WATCHシグナル】\n\n" + "\n\n".join(new_watches))
    for msg in messages:
        send_telegram(msg)

    print(f"完了: {len(results)}銘柄処理")

if __name__ == "__main__":
    main()
