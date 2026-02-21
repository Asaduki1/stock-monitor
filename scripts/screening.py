import yfinance as yf
import json
import time
from datetime import datetime

STOCK_CODES = [
    "1332","1333","1605","1721","1801","1802","1803","1808","1812","1925",
    "1928","2002","2269","2282","2413","2432","2501","2502","2503","2531",
    "2593","2651","2702","2768","2801","2802","2871","2897","2914","3086",
    "3088","3099","3101","3105","3116","3141","3197","3288","3382","3402",
    "3404","3407","3433","3436","3481","3563","3659","3861","3863","3865",
    "4004","4005","4021","4042","4043","4061","4063","4064","4091","4183",
    "4188","4208","4272","4324","4385","4452","4502","4503","4506","4507",
    "4519","4523","4527","4543","4568","4578","4661","4689","4704","4751",
    "4755","4812","4901","4902","4911","5001","5002","5019","5020","5101",
    "5105","5108","5110","5201","5202","5214","5232","5233","5301","5332",
    "5333","5401","5406","5407","5411","5413","5414","5418","5423","5440",
    "5463","5471","5480","5486","5541","5631","5706","5707","5711","5713",
    "5714","5715","5726","5727","5741","5801","5802","5803","5831","5901",
    "5938","5949","6103","6178","6201","6268","6273","6301","6302","6305",
    "6326","6361","6367","6383","6395","6412","6417","6460","6471","6472",
    "6473","6474","6479","6501","6503","6504","6506","6526","6532","6586",
    "6594","6645","6674","6702","6706","6724","6728","6752","6753","6758",
    "6762","6770","6857","6861","6902","6954","6971","6981","7003","7011",
    "7012","7013","7201","7202","7203","7205","7211","7261","7267","7269",
    "7270","7272","7282","7731","7733","7735","7741","7751","7752","7762",
    "7832","7974","8001","8002","8003","8004","8005","8006","8007","8008",
    "8031","8035","8053","8058","8063","8064","8065","8066","8267","8282",
    "8301","8304","8305","8306","8308","8309","8316","8411","8473","8593",
    "8601","8602","8604","8630","8697","8725","8750","8766","8795","8801",
    "8802","8803","8804","8830","9001","9003","9005","9006","9007","9008",
    "9009","9020","9021","9022","9064","9101","9102","9104","9107","9201",
    "9202","9432","9433","9434","9501","9502","9503","9504","9531","9532",
    "9613","9681","9684","9697","9735","9766","9983","9984"
]

def score_stock(code):
    try:
        ticker = yf.Ticker(f"{code}.T")
        info = ticker.info
        hist = ticker.history(period="1y")

        if hist.empty or len(hist) < 50:
            return None

        price = hist["Close"].iloc[-1]
        if price <= 0:
            return None

        score = 0
        conditions = {}

        # 1. 配当利回り3%以上
        div_yield = info.get("dividendYield", 0) or 0
        div_yield_pct = round(div_yield * 100, 2)
        conditions["利回り3%以上"] = div_yield_pct >= 3.0
        if conditions["利回り3%以上"]: score += 1

        # 2. 配当性向30%以下
        payout = info.get("payoutRatio", None)
        payout_pct = round(payout * 100, 1) if payout else None
        conditions["配当性向30%以下"] = payout_pct is not None and payout_pct <= 30
        if conditions["配当性向30%以下"]: score += 1

        # 3. PBR1倍割れ
        pbr = info.get("priceToBook", None)
        conditions["PBR1倍割れ"] = pbr is not None and pbr < 1.0
        if conditions["PBR1倍割れ"]: score += 1

        # 4. 75日移動平均に接近（-5%〜+3%以内）
        if len(hist) >= 75:
            ma75 = hist["Close"].rolling(75).mean().iloc[-1]
            divergence75 = round((price - ma75) / ma75 * 100, 2)
            conditions["75MA接近"] = -5 <= divergence75 <= 3
        else:
            divergence75 = None
            conditions["75MA接近"] = False
        if conditions["75MA接近"]: score += 1

        # 5. 200日移動平均に接近（-5%〜+3%以内）
        if len(hist) >= 200:
            ma200 = hist["Close"].rolling(200).mean().iloc[-1]
            divergence200 = round((price - ma200) / ma200 * 100, 2)
            conditions["200MA接近"] = -5 <= divergence200 <= 3
        else:
            divergence200 = None
            conditions["200MA接近"] = False
        if conditions["200MA接近"]: score += 1

        # スコア判定
        if score >= 5:
            signal = "BUY"
        elif score >= 3:
            signal = "WATCH"
        else:
            return None

        name = info.get("shortName") or info.get("longName") or code

        return {
            "code": code,
            "name": name,
            "price": round(price, 1),
            "yield": div_yield_pct,
            "pbr": round(pbr, 2) if pbr else None,
            "payout": payout_pct,
            "ma75_div": divergence75,
            "ma200_div": divergence200,
            "score": score,
            "signal": signal,
            "conditions": {k: int(v) for k, v in conditions.items()},
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    except Exception:
        return None


def main():
    print(f"スクリーニング開始: {len(STOCK_CODES)}銘柄")
    results = []

    for i, code in enumerate(STOCK_CODES):
        if i % 50 == 0:
            print(f"  進捗: {i}/{len(STOCK_CODES)}")
        result = score_stock(code)
        if result:
            results.append(result)
        time.sleep(0.3)

    results.sort(key=lambda x: x["score"], reverse=True)

    with open("data/screening.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"完了: {len(results)}銘柄がBUY/WATCH条件を満たしました")


if __name__ == "__main__":
    main()
