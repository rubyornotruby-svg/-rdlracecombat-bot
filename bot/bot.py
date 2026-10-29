"""
RDLRACECOMBAT — bot V2 en PAPER TRADING (aucun argent réel, aucune clé API, aucun ordre réel).

Toutes les 4 h (GitHub Actions), le bot :
  1. lit les bougies 4 h publiques de Binance pour 20 cryptos (data-api.binance.vision, sans clé) ;
  2. rejoue toutes les bougies pas encore traitées depuis son dernier passage (rattrapage) ;
  3. applique la règle V2 testée :
       - signal par crypto : cassure du plus haut des 50 bougies précédentes -> en position,
         clôture sous le plus bas des 20 bougies précédentes -> sortie ;
       - décision à la clôture, exécution au prix d'ouverture de la bougie suivante ;
       - BTC = cœur à 20 % du capital, autres cryptos 3 % chacune, 8 au maximum ;
       - autres cryptos achetées seulement si BTC est lui-même en signal BUY ;
       - total investi <= 4 x (capital - plancher x 1,02) ;
       - plancher 90 000 : si le capital tombe à 91 800, tout est vendu et le bot s'arrête ;
       - frais 0,10 % à l'achat et à la vente ;
  4. enregistre son état (state.json) et les données du site (docs/data.json).

Mode test hors ligne :  python bot.py --offline FICHIER.csv --start 2023-01-01 --until 2024-01-01
"""
import argparse, json, os, sys, time, urllib.request
from datetime import datetime, timezone

SYMS = ["BTC","ETH","BNB","XRP","SOL","ADA","DOGE","TRX","LINK","AVAX",
        "DOT","LTC","BCH","XLM","ATOM","ETC","NEAR","UNI","FIL","AAVE"]
P = dict(capital0=102120.46, floor=90000.0, margin=0.02, pct_btc=0.20, pct_alt=0.03,
         max_alt=8, cppi=4.0, fee=0.001, len_in=50, len_out=20)
H4 = 4 * 3600 * 1000
API = "https://data-api.binance.vision/api/v3/klines?symbol={s}USDT&interval=4h&limit={n}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state.json")
SITE = os.path.join(ROOT, "docs", "data.json")


# ----------------------------------------------------------------- données
def fetch(sym, n=1000):
    """Bougies 4 h (open_time_ms, o, h, l, c, close_time_ms) — données publiques Binance."""
    url = API.format(s=sym, n=n)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "rdlracecombat-paper-bot"}), timeout=20) as r:
                raw = json.load(r)
            return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), int(k[6])) for k in raw]
        except Exception as e:
            err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Prix indisponibles pour {sym} : {err}")


def load_offline(path, until_ms):
    import csv
    out = {s: [] for s in SYMS}
    with open(path) as f:
        for row in csv.DictReader(f):
            s = row["sym"]
            if s in out:
                t = int(row["t"])
                if t + H4 <= until_ms + H4:      # on garde jusqu'à la bougie qui s'ouvre à "until"
                    out[s].append((t, float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"]), t + H4 - 1))
    for s in out:
        out[s].sort()
    return out


# ----------------------------------------------------------------- signaux
def states(bars):
    """Etat (0/1) à la clôture de chaque bougie : identique au backtest (multi.signals avant décalage)."""
    st, out = 0, []
    for i, (_, o, h, l, c, _) in enumerate(bars):
        if i >= P["len_in"]:
            hh = max(b[2] for b in bars[i - P["len_in"]:i])
            if st == 0 and c > hh:
                st = 1
        if i >= P["len_out"] and st == 1:
            llx = min(b[3] for b in bars[i - P["len_out"]:i])
            if c < llx:
                st = 0
        out.append(st)
    return out


def exit_level(bars):
    """Niveau de sortie actuel (plus bas des 20 dernières bougies clôturées)."""
    return min(b[3] for b in bars[-P["len_out"]:]) if len(bars) >= P["len_out"] else None


# ----------------------------------------------------------------- moteur
def new_state(start_ms):
    return dict(version=1, start=start_ms, cash=P["capital0"], positions={}, last_open=start_ms - H4,
                halted=False, journal=[], history=[], warnings=[])


def step(S, t_open, opens, sig_now, sig_prev):
    """Traite l'ouverture de la bougie t_open (exécutions au prix d'ouverture)."""
    fee = P["fee"]
    pos = S["positions"]
    for s, p in opens.items():
        if s in pos:
            pos[s]["last"] = p
    equity = S["cash"] + sum(v["qty"] * v["last"] for v in pos.values())
    if S["halted"]:
        return equity
    # plancher
    if equity <= P["floor"] * (1 + P["margin"]):
        for s in list(pos):
            v = pos.pop(s)
            proceeds = v["qty"] * v["last"] * (1 - fee)
            S["cash"] += proceeds
            S["journal"].append(dict(sym=s, entry_time=v["time"], entry=v["entry"], exit_time=t_open, exit=v["last"],
                                     pnl=round(proceeds - v["cost"], 2), r=round(proceeds / v["cost"] - 1, 5), reason="Plancher"))
        S["halted"] = True
        S["warnings"].append(dict(time=t_open, msg="Plancher atteint : tout est vendu, le bot est arrêté."))
        return S["cash"]
    # sorties
    for s in list(pos):
        if s in opens and sig_now.get(s) == 0:
            v = pos.pop(s)
            p = opens[s]
            proceeds = v["qty"] * p * (1 - fee)
            S["cash"] += proceeds
            S["journal"].append(dict(sym=s, entry_time=v["time"], entry=v["entry"], exit_time=t_open, exit=p,
                                     pnl=round(proceeds - v["cost"], 2), r=round(proceeds / v["cost"] - 1, 5), reason="Sortie"))
    # entrées (ordre fixe : BTC d'abord, puis la liste)
    for s in SYMS:
        if s in pos or s not in opens:
            continue
        if not (sig_now.get(s) == 1 and sig_prev.get(s) == 0):
            continue
        if s != "BTC":
            if sig_now.get("BTC") != 1:
                continue
            if sum(1 for k in pos if k != "BTC") >= P["max_alt"]:
                continue
        amt = equity * (P["pct_btc"] if s == "BTC" else P["pct_alt"])
        invested = sum(v["qty"] * v["last"] for v in pos.values())
        amt = min(amt, P["cppi"] * (equity - P["floor"] * (1 + P["margin"])) - invested)
        if amt < 0.01 * equity or S["cash"] < amt:
            continue
        p = opens[s]
        pos[s] = dict(qty=amt * (1 - fee) / p, cost=amt, entry=p, last=p, time=t_open)
        S["cash"] -= amt
    return S["cash"] + sum(v["qty"] * v["last"] for v in pos.values())


def run(S, data, now_ms):
    """Rejoue toutes les ouvertures de bougies 4 h postérieures à S['last_open'] et déjà commencées."""
    sig = {s: states([b for b in data[s] if b[5] < now_ms]) for s in SYMS if data.get(s)}
    # index : open_time -> (open, état à la clôture de la bougie précédente)
    idx = {}
    for s in sig:
        closed = [b for b in data[s] if b[5] < now_ms]
        times = [b[0] for b in data[s]]
        for i, b in enumerate(data[s]):
            if i == 0:
                continue
            j = i - 1                                   # bougie précédente (clôturée)
            if j >= len(closed):
                continue
            prev2 = sig[s][j - 1] if j >= 1 else None
            idx.setdefault(b[0], {})[s] = (b[1], sig[s][j], prev2)
    done = 0
    for t in sorted(idx):
        if t <= S["last_open"] or t < S["start"] or t > now_ms:
            continue
        opens = {s: v[0] for s, v in idx[t].items()}
        now_sig = {s: v[1] for s, v in idx[t].items()}
        prev_sig = {s: v[2] for s, v in idx[t].items()}
        eq = step(S, t, opens, now_sig, prev_sig)
        S["last_open"] = t
        S["history"].append([t, round(eq, 2)])
        done += 1
    return sig, done


# ----------------------------------------------------------------- site
def site_data(S, data, sig, now_ms):
    pos = S["positions"]
    equity = S["cash"] + sum(v["qty"] * v["last"] for v in pos.values())
    closed = S["journal"]
    wins = sum(1 for j in closed if j["pnl"] > 0)
    market = []
    for s in SYMS:
        bars = [b for b in data.get(s, []) if b[5] < now_ms]
        if not bars:
            continue
        st = sig[s][-1]
        state = "BUY" if (s in pos) else ("Sortie" if st == 0 and len(sig[s]) > 1 and sig[s][-2] == 1 else ("Signal" if st == 1 else "Attendre"))
        market.append(dict(sym=s, close=bars[-1][4], state=state, exit_level=exit_level(bars)))
    positions = []
    for s, v in pos.items():
        bars = [b for b in data.get(s, []) if b[5] < now_ms]
        positions.append(dict(sym=s, size=round(v["cost"] / P["capital0"] * 100, 1), entry=v["entry"], last=v["last"],
                              stop=exit_level(bars), qty=v["qty"], cost=v["cost"], since=v["time"]))
    return dict(updated=now_ms, next_run=(S["last_open"] + H4 + 5 * 60 * 1000), start=S["start"], params=P,
                capital0=P["capital0"], equity=round(equity, 2), cash=round(S["cash"], 2), halted=S["halted"],
                floor=P["floor"], trades=len(closed), wins=wins, positions=positions, market=market,
                journal=list(reversed(closed[-100:])), history=S["history"][-2200:], warnings=S["warnings"][-20:])


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline")
    ap.add_argument("--start")
    ap.add_argument("--until")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    def ms(d):
        return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000)

    if a.offline:
        now_ms = ms(a.until)
        data = load_offline(a.offline, now_ms)
        S = json.load(open(a.state)) if a.resume and os.path.exists(a.state) else new_state(ms(a.start))
    else:
        now_ms = int(time.time() * 1000)
        data = {s: fetch(s) for s in SYMS}            # une erreur = on ne touche à rien (rattrapage au prochain passage)
        if os.path.exists(a.state):
            S = json.load(open(a.state))
        else:
            S = new_state((now_ms // H4) * H4 - H4)  # démarrage : dernière bougie ouverte
    sig, done = run(S, data, now_ms)
    out = site_data(S, data, sig, now_ms)
    os.makedirs(os.path.dirname(a.site), exist_ok=True)
    json.dump(S, open(a.state, "w"), separators=(",", ":"))
    json.dump(out, open(a.site, "w"), separators=(",", ":"))
    print(f"Bougies traitées : {done} | capital : {out['equity']:,.2f} | positions : {len(out['positions'])} | "
          f"trades clôturés : {out['trades']} | arrêté : {out['halted']}")


if __name__ == "__main__":
    main()
