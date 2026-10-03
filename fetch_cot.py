#!/usr/bin/env python3
"""
Завантажує тижневі дані CFTC (Commitments of Traders) і збирає docs/data.js
для дашборда. Лише стандартна бібліотека Python, ключі не потрібні.

Звіти:
  TFF  (gpe5-46if)  - Traders in Financial Futures, futures only:
                      валюти, індекси, ставки, VIX, крипто.
                      Групи: Leveraged funds (lev_money) і Asset managers (asset_mgr).
  DISAGG (72hh-3qpy) - Disaggregated, futures only:
                      метали, енергія, агро.
                      Групи: Managed money (m_money) і Producer/Merchant (prod_merc).

Запуск:   python fetch_cot.py            (реальні дані)
          python fetch_cot.py --demo     (синтетичні дані для перевірки інтерфейсу)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://publicreporting.cftc.gov/resource/"
TFF = "gpe5-46if"
DISAGG = "72hh-3qpy"
HISTORY_YEARS = 6
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data.js")

# (код контракту CFTC, ключ, назва, категорія, пара/підказка, інверсія для пар з USD на першому місці)
TFF_MARKETS = [
    ("099741", "EUR", "Євро", "FX", "EURUSD", False),
    ("096742", "GBP", "Британський фунт", "FX", "GBPUSD", False),
    ("097741", "JPY", "Японська єна", "FX", "USDJPY", True),
    ("092741", "CHF", "Швейцарський франк", "FX", "USDCHF", True),
    ("232741", "AUD", "Австралійський долар", "FX", "AUDUSD", False),
    ("090741", "CAD", "Канадський долар", "FX", "USDCAD", True),
    ("112741", "NZD", "Новозеландський долар", "FX", "NZDUSD", False),
    ("095741", "MXN", "Мексиканське песо", "FX", "USDMXN", True),
    ("102741", "BRL", "Бразильський реал", "FX", "USDBRL", True),
    ("122741", "ZAR", "Південноафриканський ранд", "FX", "USDZAR", True),
    ("098662", "DXY", "Індекс долара США", "FX", "DXY", False),
    ("13874A", "ES", "S&P 500 (E-mini)", "Індекси", "US500", False),
    ("209742", "NQ", "Nasdaq 100 (E-mini)", "Індекси", "US100", False),
    ("239742", "RTY", "Russell 2000 (E-mini)", "Індекси", "US2000", False),
    ("124603", "YM", "Dow Jones (x$5)", "Індекси", "US30", False),
    ("1170E1", "VIX", "VIX", "Індекси", "VIX", False),
    ("042601", "ZT", "UST 2Y", "Ставки", "US02Y", False),
    ("044601", "ZF", "UST 5Y", "Ставки", "US05Y", False),
    ("043602", "ZN", "UST 10Y", "Ставки", "US10Y", False),
    ("020601", "ZB", "UST Bond", "Ставки", "US30Y", False),
    ("133741", "BTC", "Bitcoin (CME)", "Крипто", "BTCUSD", False),
    ("146021", "ETH", "Ether (CME)", "Крипто", "ETHUSD", False),
]

DISAGG_MARKETS = [
    ("088691", "XAU", "Золото", "Метали", "XAUUSD", False),
    ("084691", "XAG", "Срібло", "Метали", "XAGUSD", False),
    ("085692", "HG", "Мідь", "Метали", "Copper", False),
    ("076651", "XPT", "Платина", "Метали", "XPTUSD", False),
    ("075651", "XPD", "Паладій", "Метали", "XPDUSD", False),
    ("067651", "CL", "Нафта WTI", "Енергія", "USOIL", False),
    ("023651", "NG", "Природний газ", "Енергія", "NatGas", False),
    ("002602", "ZC", "Кукурудза", "Агро", "Corn", False),
    ("001602", "ZW", "Пшениця", "Агро", "Wheat", False),
    ("005602", "ZS", "Соя", "Агро", "Soybeans", False),
]

# Кандидати назв полів: CFTC інколи має опечатки, тому пробуємо кілька варіантів.
TFF_FIELDS = {
    "A": {"long": ["lev_money_positions_long", "lev_money_positions_long_all"],
          "short": ["lev_money_positions_short", "lev_money_positions_short_all"]},
    "B": {"long": ["asset_mgr_positions_long", "asset_mgr_positions_long_all"],
          "short": ["asset_mgr_positions_short", "asset_mgr_positions_short_all"]},
}
DISAGG_FIELDS = {
    "A": {"long": ["m_money_positions_long_all", "m_money_positions_long"],
          "short": ["m_money_positions_short_all", "m_money_positions_short"]},
    "B": {"long": ["prod_merc_positions_long", "prod_merc_positions_long_all"],
          "short": ["prod_merc_positions_short", "prod_merc_positions_short_all"]},
}
OI_FIELDS = ["open_interest_all"]
DATE_FIELD = "report_date_as_yyyy_mm_dd"
CODE_FIELD = "cftc_contract_market_code"

# Тікери Yahoo для ціни (необов'язково; якщо не вдалось - дашборд працює без ціни)
YAHOO = {
    "EUR": "EURUSD=X", "GBP": "GBPUSD=X", "JPY": "JPY=X", "CHF": "CHF=X", "AUD": "AUDUSD=X",
    "CAD": "CAD=X", "NZD": "NZDUSD=X", "MXN": "MXN=X", "BRL": "BRL=X", "ZAR": "ZAR=X",
    "DXY": "DX-Y.NYB", "ES": "ES=F", "NQ": "NQ=F", "RTY": "RTY=F", "YM": "YM=F", "VIX": "^VIX",
    "ZN": "ZN=F", "ZB": "ZB=F", "ZF": "ZF=F", "ZT": "ZT=F", "BTC": "BTC-USD", "ETH": "ETH-USD",
    "XAU": "GC=F", "XAG": "SI=F", "HG": "HG=F", "XPT": "PL=F", "XPD": "PA=F",
    "CL": "CL=F", "NG": "NG=F", "ZC": "ZC=F", "ZW": "ZW=F", "ZS": "ZS=F",
}


def http_get(url, timeout=60, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cot-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url[:120]}... -> {last}")


def fetch_rows(dataset, codes, since):
    codes_sql = ",".join(f"'{c}'" for c in codes)
    where = f"{CODE_FIELD} in({codes_sql}) AND {DATE_FIELD} >= '{since}'"
    params = {"$where": where, "$order": f"{DATE_FIELD} ASC", "$limit": "50000"}
    token = os.environ.get("CFTC_APP_TOKEN")
    if token:
        params["$$app_token"] = token
    url = f"{BASE}{dataset}.json?{urllib.parse.urlencode(params)}"
    return json.loads(http_get(url))


def pick(row, candidates):
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return int(float(row[c]))
    return None


def build_group_series(rows, fields, warnings, label):
    """Повертає dict: dates, oi, A_long, A_short, B_long, B_short."""
    rows = sorted(rows, key=lambda r: r[DATE_FIELD])
    out = {"dates": [], "oi": [], "A_long": [], "A_short": [], "B_long": [], "B_short": []}
    for r in rows:
        vals = {
            "oi": pick(r, OI_FIELDS),
            "A_long": pick(r, fields["A"]["long"]),
            "A_short": pick(r, fields["A"]["short"]),
            "B_long": pick(r, fields["B"]["long"]),
            "B_short": pick(r, fields["B"]["short"]),
        }
        if any(v is None for v in vals.values()):
            warnings.append(f"{label}: пропущено рядок {r.get(DATE_FIELD, '?')[:10]} (немає поля)")
            continue
        out["dates"].append(r[DATE_FIELD][:10])
        for k, v in vals.items():
            out[k].append(v)
    return out


def fetch_prices(ticker, since_ts):
    """Тижневі закриття з Yahoo (неофіційний endpoint, best-effort)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
           f"?range=7y&interval=1wk")
    data = json.loads(http_get(url, timeout=30, retries=2))
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    pts = []
    for t, c in zip(ts, closes):
        if c is None or t < since_ts:
            continue
        pts.append([datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), round(float(c), 5)])
    return pts


def demo_series(seed, n=312, start=datetime(2020, 9, 29)):
    import math
    import random
    rnd = random.Random(seed)
    dates, oi, al, as_, bl, bs = [], [], [], [], [], []
    base_oi = rnd.randint(60_000, 700_000)
    phase = rnd.random() * 6
    for i in range(n):
        d = start + timedelta(days=7 * i)
        dates.append(d.strftime("%Y-%m-%d"))
        o = int(base_oi * (1 + 0.25 * math.sin(i / 20 + phase) + rnd.uniform(-0.03, 0.03)))
        oi.append(o)
        net_a = int(o * (0.22 * math.sin(i / 26 + phase) + rnd.uniform(-0.02, 0.02)))
        net_b = int(o * (-0.15 * math.sin(i / 30 + phase * 0.7) + rnd.uniform(-0.02, 0.02)))
        la = int(o * 0.2) + max(net_a, 0)
        sa = la - net_a
        lb = int(o * 0.25) + max(net_b, 0)
        sb = lb - net_b
        al.append(max(la, 0)); as_.append(max(sa, 0)); bl.append(max(lb, 0)); bs.append(max(sb, 0))
    return {"dates": dates, "oi": oi, "A_long": al, "A_short": as_, "B_long": bl, "B_short": bs}


def demo_prices(dates, seed):
    import math
    import random
    rnd = random.Random(seed + 99)
    p = 100.0
    out = []
    for i, d in enumerate(dates):
        p *= 1 + 0.01 * math.sin(i / 11) * 0.6 + rnd.uniform(-0.012, 0.012)
        out.append([d, round(p, 4)])
    return out


def main():
    demo = "--demo" in sys.argv
    warnings = []
    since = (datetime.now(timezone.utc) - timedelta(days=365 * HISTORY_YEARS)).strftime("%Y-%m-%d")
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=365 * HISTORY_YEARS)).timestamp())

    markets = []
    groups_cfg = [
        (TFF, TFF_MARKETS, TFF_FIELDS, "TFF",
         {"A": "Leveraged funds", "B": "Asset managers"}),
        (DISAGG, DISAGG_MARKETS, DISAGG_FIELDS, "DISAGG",
         {"A": "Managed money", "B": "Producer/Merchant"}),
    ]
    for dataset, defs, fields, kind, names in groups_cfg:
        if demo:
            rows_by_code = None
        else:
            rows = fetch_rows(dataset, [m[0] for m in defs], since)
            rows_by_code = {}
            for r in rows:
                rows_by_code.setdefault(r[CODE_FIELD].strip(), []).append(r)
        for i, (code, key, name, cat, pair, invert) in enumerate(defs):
            if demo:
                series = demo_series(sum(ord(ch) for ch in key) + i)
            else:
                mrows = rows_by_code.get(code, [])
                if not mrows:
                    warnings.append(f"{key} ({code}): CFTC не повернув даних")
                    continue
                series = build_group_series(mrows, fields, warnings, key)
                if len(series["dates"]) < 20:
                    warnings.append(f"{key} ({code}): замало даних ({len(series['dates'])} тижнів)")
                    continue
            m = {"key": key, "code": code, "name": name, "cat": cat, "pair": pair,
                 "invert": invert, "kind": kind, "groupNames": names, "series": series, "price": []}
            if demo:
                m["price"] = demo_prices(series["dates"], i)
            elif key in YAHOO:
                try:
                    m["price"] = fetch_prices(YAHOO[key], since_ts)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"{key}: ціну не завантажено ({str(e)[:80]})")
            markets.append(m)

    if not markets:
        print("ПОМИЛКА: жодного ринку не завантажено, data.js не оновлено", file=sys.stderr)
        for w in warnings:
            print(" -", w, file=sys.stderr)
        sys.exit(1)

    last_report = max(m["series"]["dates"][-1] for m in markets)
    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "lastReport": last_report,
        "demo": demo,
        "warnings": warnings,
        "markets": markets,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("window.COT_DATA = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(f"OK: {len(markets)} ринків, останній звіт {last_report}, файл {OUT_PATH}")
    for w in warnings:
        print(" !", w)


if __name__ == "__main__":
    main()
