import json
import requests
import pandas as pd
import os
from datetime import datetime, timedelta

JQUANTS_REFRESH_TOKEN = os.environ.get("JQUANTS_REFRESH_TOKEN")

# ===== J-Quants認証 =====
def get_id_token():
    # APIキー方式
    return JQUANTS_REFRESH_TOKEN

# ===== 全銘柄リスト取得 =====
def get_all_stocks(id_token):
    res = requests.get(
        "https://api.jquants.com/v1/listed/info",
        headers={"Authorization": f"Bearer {id_token}"}
    )
    data = res.json().get("info", [])
    # 東証プライム・スタンダード・グロースのみ
    return [s for s in data if s.get("MarketCodeName") in [
        "プライム（内国株式）",
        "スタンダード（内国株式）"
    ]]

# ===== 株価取得 =====
def get_prices(id_token, code):
    today = datetime.now()
    from_date = (today - timedelta(days=300)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    res = requests.get(
        "https://api.jquants.com/v1/prices/daily_quotes",
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
        "https://api.jquants.com/v1/fins/statements",
        headers={"Authorization": f"Bearer {id_token}"},
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
    if not annual:
        annual = data
    return annual[-1]

# ===== 指標計算 =====
def calc_indicators(df):
    close = df["AdjustmentClose"].astype(float)
    price = round(close.iloc[-1], 1)
    ma75 = round(close.rolling(75).mean().iloc[-1], 1) if len(close) >= 75 else None
    ma200 = round(close.rolling(200).mean().iloc[-1], 1) if len(close) >= 200 else None
    div75 = round((price - ma75) / ma75 * 100, 2) if ma75 else None
    div200 = round((price - ma200) / ma200 * 100, 2) if ma200 else None
    return price, div75, div200

# ===== スコアリング =====
def score_stock(id_token, stock_info):
    code = stock_info["Code"]
    name = stock_info.get("CompanyName", code)

    try:
        df = get_prices(id_token, code)
        if df is None or len(df) < 50:
            return None

        price, div75, div200 = calc_indicators(df)
        if price <= 0:
            return None

        fins = get_financials(id_token, code)
        if not fins:
            return None

        score = 0
        conditions = {}

        # 1. 配当利回り3%以上
        div_per_share = fins.get("AnnualDividendPerShare")
        div_yield = 0
        if div_per_share and float(div_per_share) > 0:
            div_yield = round(float(div_per_share) / price * 100, 2)
        conditions["利回り3%以上"] = int(div_yield >= 3.0)
        if conditions["利回り3%以上"]: score += 1

        # 2. 配当性向30%以下
        payout = fins.get("PayoutRatio")
        payout_pct = round(float(payout), 1) if payout and float(payout) > 0 else None
        conditions["配当性向30%以下"] = int(payout_pct is not None and payout_pct <= 30)
        if conditions["配当性向30%以下"]: score += 1

        # 3. PBR1倍割れ
        pbr = fins.get("PriceBookValueRatio")
        pbr_val = round(float(pbr), 2) if pbr and float(pbr) > 0 else None
        conditions["PBR1倍割れ"] = int(pbr_val is not None and pbr_val < 1.0)
        if conditions["PBR1倍割れ"]: score += 1

        # 最低条件チェック
        if not (conditions["利回り3%以上"] and conditions["配当性向30%以下"] and conditions["PBR1倍割れ"]):
            return None

        # 4. 75日MA接近
        conditions["75MA接近"] = int(div75 is not None and -5 <= div75 <= 3)
        if conditions["75MA接近"]: score += 1

        # 5. 200日MA接近
        conditions["200MA接近"] = int(div200 is not None and -5 <= div200 <= 3)
        if conditions["200MA接近"]: score += 1

        # シグナル判定
        if score >= 5:
            signal = "BUY"
        elif score >= 3:
            signal = "WATCH"
        else:
            return None

        return {
            "code": code,
            "name": name,
            "price": price,
            "yield": div_yield,
            "pbr": pbr_val,
            "payout": payout_pct,
            "ma75_div": div75,
            "ma200_div": div200,
            "score": score,
            "signal": signal,
            "conditions": conditions,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    except Exception as e:
        print(f"  {code} エラー: {e}")
        return None


def main():
    print("J-Quants認証中...")
    id_token = get_id_token()

    print("銘柄リスト取得中...")
    stocks = get_all_stocks(id_token)
    print(f"対象銘柄数: {len(stocks)}")

    results = []
    for i, stock in enumerate(stocks):
        if i % 100 == 0:
            print(f"  進捗: {i}/{len(stocks)}")
        result = score_stock(id_token, stock)
        if result:
            results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)

    with open("data/screening.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"完了: {len(results)}銘柄がBUY/WATCH条件を満たしました")


if __name__ == "__main__":
    main()
