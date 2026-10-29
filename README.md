# RDLRACECOMBAT — bot de paper trading

**Simulation uniquement : aucun argent réel, aucune clé API, aucun ordre réel.**

- `bot/bot.py` : le bot (règle V2 testée). Il lit les prix publics de Binance toutes les 2 heures.
- `.github/workflows/bot.yml` : lancement automatique toutes les 2 heures par GitHub Actions.
- `docs/` : le tableau de bord (GitHub Pages), qui lit `docs/data.json`.
- `state.json` : l'état du bot (capital, positions, journal). Ne pas modifier à la main.

Règles : cassure 50 / 20 en 2 h · BTC 20 % · autres cryptos 3 % (8 max) · filtre BTC ·
plancher 85 000 € (pause + question à 86 700 €, 10 min pour répondre « continuer » ou « vendre » dans l’issue GitHub) · dernière limite 75 000 € (vente automatique à 76 500 €) · frais 0,10 %.
