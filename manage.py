"""
Gestión de operaciones: cerrar manualmente cuando un mercado resuelve.
Uso:
  python manage.py list
  python manage.py close <id> yes
  python manage.py close <id> no
  python manage.py stats
  python manage.py reset
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

DATA_FILE = Path("data/trades.json")
INITIAL_BALANCE = 1000.0

def load():
    if not DATA_FILE.exists():
        print("Sin datos todavia. Ejecuta bot.py primero.")
        sys.exit(1)
    with open(DATA_FILE) as f:
        return json.load(f)

def save(state):
    with open(DATA_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def cmd_list(state):
    open_trades = [t for t in state["trades"] if t["status"] == "open"]
    if not open_trades:
        print("No hay operaciones abiertas.")
        return
    print(f"\n{'ID':<6} {'Lado':<5} {'Monto':>8} {'EV':>7}  Mercado")
    print("-" * 80)
    for i, t in enumerate(open_trades):
        print(f"{i:<6} {t['side']:<5} ${t['amount']:>7.2f} {t['ev']*100:>6.1f}%  {t['question'][:50]}...")
    print(f"\nBalance disponible: ${state['balance']:.2f}")

def cmd_close(state, trade_idx, won):
    open_trades = [t for t in state["trades"] if t["status"] == "open"]
    if trade_idx >= len(open_trades):
        print(f"ID {trade_idx} no existe.")
        return
    trade = open_trades[trade_idx]
    trade["status"]    = "won" if won else "lost"
    trade["closed_at"] = now_iso()
    if won:
        payout = trade["amount"] / trade["poly_prob"]
        profit = payout - trade["amount"]
        trade["pnl"]         = round(profit, 2)
        trade["close_price"] = 1.0
        state["balance"]    += payout
        print(f"Ganaste: +${profit:.2f} | Nuevo balance: ${state['balance']:.2f}")
    else:
        trade["pnl"]         = -round(trade["amount"], 2)
        trade["close_price"] = 0.0
        print(f"Perdiste: -${trade['amount']:.2f} | Nuevo balance: ${state['balance']:.2f}")
    curve = state.get("equity_curve", [])
    pt = {"date": today(), "value": round(state["balance"], 2)}
    if curve and curve[-1]["date"] == today():
        curve[-1] = pt
    else:
        curve.append(pt)
    state["equity_curve"] = curve
    save(state)

def cmd_stats(state):
    trades = state["trades"]
    closed = [t for t in trades if t["status"] in ("won", "lost")]
    won    = [t for t in closed if t["status"] == "won"]
    open_t = [t for t in trades if t["status"] == "open"]
    pnl      = sum(t["pnl"] for t in closed)
    roi      = (state["balance"] - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    win_rate = len(won) / len(closed) * 100 if closed else 0
    avg_ev   = sum(t["ev"] for t in trades) / len(trades) * 100 if trades else 0
    print("\n" + "=" * 40)
    print("  RESUMEN DE RENDIMIENTO")
    print("=" * 40)
    print(f"  Balance actual:  ${state['balance']:>8.2f}")
    print(f"  P&L total:       ${pnl:>+8.2f}")
    print(f"  ROI:             {roi:>+7.1f}%")
    print(f"  Win rate:        {win_rate:>7.1f}%  ({len(won)}/{len(closed)})")
    print(f"  EV promedio:     {avg_ev:>+7.1f}%")
    print(f"  Operaciones:     {len(trades):>7}  ({len(open_t)} abiertas)")
    print("=" * 40)

def cmd_reset(state):
    confirm = input("Escribe RESET para confirmar: ")
    if confirm == "RESET":
        save({"balance": INITIAL_BALANCE, "trades": [], "equity_curve": [{"date": today(), "value": INITIAL_BALANCE}], "runs": []})
        print("Estado reiniciado a $1,000.00")
    else:
        print("Cancelado.")

if __name__ == "__main__":
    args = sys.argv[1:]
    state = load()
    if not args or args[0] == "list":
        cmd_list(state)
    elif args[0] == "stats":
        cmd_stats(state)
    elif args[0] == "reset":
        cmd_reset(state)
    elif args[0] == "close" and len(args) >= 3:
        try:
            cmd_close(state, int(args[1]), args[2].lower() in ("yes","si","1","true","won"))
        except ValueError:
            print("Uso: python manage.py close <numero> yes|no")
    else:
        print(__doc__)
