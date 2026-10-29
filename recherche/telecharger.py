"""Télécharge les bougies 1 h publiques Binance (sans clé) des 20 cryptos du bot, 2021-01 -> maintenant."""
import json, time, urllib.request, gzip, csv
SYMS = ["BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","LINK","AVAX","DOT","LTC","BCH","XLM","ATOM","ETC","NEAR","UNI","FIL","AAVE"]
URL = "https://data-api.binance.vision/api/v3/klines?symbol={s}USDT&interval=1h&startTime={t}&limit=1000"
start0 = 1609459200000 - 30 * 86400000          # 2020-12-02, pour l'historique des 50 bougies
with gzip.open("recherche/crypto-1h.csv.gz", "wt", newline="") as f:
    w = csv.writer(f); w.writerow(["sym", "t", "o", "h", "l", "c"])
    for s in SYMS:
        t, n = start0, 0
        while True:
            for a in range(5):
                try:
                    raw = json.load(urllib.request.urlopen(URL.format(s=s, t=t), timeout=30)); break
                except Exception as e:
                    time.sleep(3 * (a + 1))
            if not raw: break
            for k in raw:
                w.writerow([s, k[0], k[1], k[2], k[3], k[4]])
            n += len(raw); t = raw[-1][0] + 3600000
            if len(raw) < 1000: break
        print(s, n, flush=True)
