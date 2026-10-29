"""
Plancher 85 % atteint : le bot ouvre une « issue » GitHub qui te pose la question,
attend 10 minutes ta réponse en commentaire (« continuer » ou « vendre »),
puis relance le bot avec la décision. Sans réponse : « vendre ».
Paper trading uniquement. Utilise seulement le jeton automatique de GitHub Actions (GITHUB_TOKEN).
"""
import json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state.json")
REPO = os.environ["GITHUB_REPOSITORY"]
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", REPO.split("/")[0])
TOKEN = os.environ["GITHUB_TOKEN"]
WAIT = 10 * 60


def api(method, path, body=None):
    req = urllib.request.Request("https://api.github.com/repos/" + REPO + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


S = json.load(open(STATE))
pend = S.get("pending")
if not pend:
    sys.exit(0)

if not pend.get("issue"):
    eq = f"{pend['equity']:,.0f}".replace(",", " ")
    issue = api("POST", "/issues", dict(
        title="⚠️ Plancher 85 % atteint — réponds « continuer » ou « vendre » (10 min)",
        body=(f"@{OWNER} le capital simulé est à **{eq} €** (plancher 85 000 €).\n\n"
              "Réponds en commentaire ici, dans les **10 minutes** :\n"
              "- **continuer** → le bot garde ses positions et le plancher descend à **75 000 €** (dernière limite, vente automatique) ;\n"
              "- **vendre** → le bot vend tout et s'arrête.\n\n"
              "Sans réponse dans 10 minutes, le bot **vend tout et s'arrête**.\n\n_Paper trading : aucun argent réel._")))
    pend["issue"], pend["asked"] = issue["number"], time.time()
    json.dump(S, open(STATE, "w"), separators=(",", ":"))

num, deadline = pend["issue"], pend["asked"] + WAIT
decision = None
while decision is None:
    for c in api("GET", f"/issues/{num}/comments?per_page=100"):
        if c["user"]["login"].lower() != OWNER.lower():
            continue
        txt = c["body"].lower()
        if "continuer" in txt:
            decision = "continuer"; break
        if "vendre" in txt:
            decision = "vendre"; break
    if decision is None:
        if time.time() > deadline:
            decision = "vendre"; break
        time.sleep(20)

msg = ("✅ Réponse « continuer » : le plancher descend à 75 000 € (dernière limite)." if decision == "continuer"
       else "🛑 Le bot vend tout et s'arrête (réponse « vendre » ou pas de réponse en 10 minutes).")
api("POST", f"/issues/{num}/comments", dict(body=msg))
api("PATCH", f"/issues/{num}", dict(state="closed"))
print("Décision :", decision)
subprocess.run([sys.executable, os.path.join(ROOT, "bot", "bot.py"), "--decision", decision], check=True)
