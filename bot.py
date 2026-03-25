"""
Polymarket Paper Trading Bot
Estrategia: Filtro liquidez -> EV+ -> Ajuste tendencia -> Kelly moderado -> Diversificacion
Corre cada 1 hora via Railway cron
"""

import os, json, logging, requests
from datetime import datetime, timezone
from pathlib import Path
from anthropic import Anthropic

INITIAL_BALANCE    = 1000.0
MAX_PER_MARKET     = 0.15
MAX_PER_CATEGORY   = 0.35
MIN_EV_THRESHOLD   = 0.04
MIN_LIQUIDITY      = 500_000
KELLY_FRACTION     = 0.5
DATA_FILE          = Path("data/trades.json")
LOG_FILE           = Path("data/bot.log")
GAMMA_API          = "https://gamma-api.polymarket.com"

Path("data").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger("polybot")
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def load_state():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"balance": INITIAL_BALANCE, "trades": [], "equity_curve": [{"date": today(), "value": INITIAL_BALANCE}], "runs": []}

def save_state(state):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def fetch_markets(limit=50):
    try:
        resp = requests.get(f"{GAMMA_API}/markets",
            params={"active":"true","closed":"false","limit":limit,"order":"volume24hr","ascending":"false"},
            timeout=15)
        resp.raise_for_status()
        markets = resp.json()
        if isinstance(markets, dict):
            markets = markets.get("markets", [])
        log.info(f"Mercados obtenidos: {len(markets)}")
        return markets
    except Exception as e:
        log.error(f"Error fetch markets: {e}")
        return []

def parse_market(m):
    try:
        volume = float(m.get("volume",0) or m.get("volumeNum",0) or 0)
        if volume < MIN_LIQUIDITY:
            return None
        outcomes = m.get("outcomes","[]")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        prices = m.get("outcomePrices","[]")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not outcomes or not prices or len(prices) < 2:
            return None
        prob_yes = float(prices[0]) if prices[0] else None
        if prob_yes is None or not (0.03 < prob_yes < 0.97):
            return None
        return {
            "id": m.get("id") or m.get("conditionId",""),
            "question": m.get("question","Sin titulo"),
            "category": m.get("category") or m.get("groupItemTitle") or "General",
            "volume": volume, "prob_yes": prob_yes, "prob_no": 1-prob_yes,
            "end_date": m.get("endDate") or m.get("endDateIso",""),
            "url": f"https://polymarket.com/event/{m.get('slug', m.get('id',''))}",
        }
    except Exception as e:
        log.warning(f"Error parseando mercado: {e}")
        return None

def analyze_markets_with_claude(markets):
    if not markets:
        return []
    market_list = "\n".join([
        f"{i+1}. [{m['category']}] {m['question']} | Polymarket YES: {m['prob_yes']:.1%} | Vol: ${m['volume']:,.0f}"
        for i, m in enumerate(markets)
    ])
    prompt = f"""Eres un analista experto en mercados de prediccion. Analiza estos mercados y estima la probabilidad REAL de cada evento.

MERCADOS:
{market_list}

Devuelve SOLO un JSON array:
[{{"index":1,"true_prob_yes":0.55,"trend":"up","reasoning":"razon breve"}},...]

- true_prob_yes: tu estimacion real (0.0 a 1.0)
- trend: "up" / "down" / "neutral"
- reasoning: 1 frase

SOLO el JSON, sin texto adicional."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=2000,
            messages=[{"role":"user","content":prompt}]
        )
        raw = response.content[0].text.strip().replace("```json","").replace("```","").strip()
        analysis = json.loads(raw)
        result = []
        for item in analysis:
            idx = item["index"] - 1
            if 0 <= idx < len(markets):
                m = markets[idx].copy()
                m["true_prob_yes"] = float(item.get("true_prob_yes", m["prob_yes"]))
                m["true_prob_no"]  = 1 - m["true_prob_yes"]
                m["trend"]         = item.get("trend","neutral")
                m["reasoning"]     = item.get("reasoning","")
                result.append(m)
        log.info(f"Claude analizo {len(result)} mercados")
        return result
    except Exception as e:
        log.error(f"Error Claude: {e}")
        for m in markets:
            m["true_prob_yes"] = m["prob_yes"]
            m["true_prob_no"]  = m["prob_no"]
            m["trend"]         = "neutral"
            m["reasoning"]     = "Analisis no disponible"
        return markets

def calc_ev(poly_prob, true_prob):
    if poly_prob <= 0 or poly_prob >= 1:
        return -999
    return true_prob * ((1/poly_prob)-1) - (1-true_prob)

def calc_kelly(ev, prob, balance):
    if prob <= 0 or prob >= 1:
        return 0
    b = (1/prob)-1
    q = 1-prob
    kelly = (b*prob - q)/b
    return min(max(0.0, kelly*KELLY_FRACTION)*balance, balance*MAX_PER_MARKET)

def trend_adj(trend):
    return {"up":0.03,"down":-0.03,"neutral":0.0}.get(trend,0.0)

def cat_exposure(trades, category):
    return sum(t["amount"] for t in trades if t["status"]=="open" and t["category"]==category)

def decide(market, state):
    balance = state["balance"]
    trades  = state["trades"]
    adj     = trend_adj(market["trend"])
    ev_yes  = calc_ev(market["prob_yes"], market["true_prob_yes"]) + adj
    ev_no   = calc_ev(market["prob_no"],  market["true_prob_no"])  - adj

    best_side, best_ev, best_prob = None, -999, 0
    if ev_yes > ev_no and ev_yes >= MIN_EV_THRESHOLD:
        best_side, best_ev, best_prob = "YES", ev_yes, market["true_prob_yes"]
    elif ev_no >= MIN_EV_THRESHOLD:
        best_side, best_ev, best_prob = "NO",  ev_no,  market["true_prob_no"]

    if best_side is None:
        return None
    if cat_exposure(trades, market["category"]) >= balance * MAX_PER_CATEGORY:
        log.info(f"  Limite categoria '{market['category']}' alcanzado.")
        return None
    kelly = calc_kelly(best_ev, best_prob, balance)
    if kelly < 1.0:
        return None
    kelly = min(kelly, balance, balance*MAX_PER_MARKET)
    if market["id"] in {t["market_id"] for t in trades if t["status"]=="open"}:
        return None

    return {
        "market_id":  market["id"], "question": market["question"],
        "category":   market["category"], "side": best_side,
        "amount":     round(kelly, 2),
        "poly_prob":  round(market["prob_yes"] if best_side=="YES" else market["prob_no"], 4),
        "true_prob":  round(best_prob, 4), "ev": round(best_ev, 4),
        "trend":      market["trend"], "reasoning": market["reasoning"],
        "url":        market["url"], "volume": market["volume"],
        "status":     "open", "opened_at": now_iso(),
        "closed_at":  None, "pnl": 0.0, "close_price": None,
    }

def run():
    log.info("="*60)
    log.info("Iniciando ciclo del bot")
    state = load_state()
    raw   = fetch_markets(limit=60)
    parsed = [p for m in raw if (p := parse_market(m)) is not None]
    log.info(f"Mercados con liquidez suficiente: {len(parsed)}")
    if not parsed:
        log.warning("Sin mercados, abortando.")
        return
    analyzed   = analyze_markets_with_claude(parsed[:30])
    new_trades = []
    for market in sorted(analyzed, key=lambda x: x.get("volume",0), reverse=True):
        if state["balance"] < 5:
            break
        trade = decide(market, state)
        if trade:
            state["balance"] -= trade["amount"]
            state["trades"].append(trade)
            new_trades.append(trade)
            log.info(f"  TRADE: {trade['side']} ${trade['amount']:.2f} EV={trade['ev']:.1%} {trade['question'][:50]}...")
    curve = state.get("equity_curve",[])
    pt    = {"date": today(), "value": round(state["balance"],2)}
    if curve and curve[-1]["date"] == today():
        curve[-1] = pt
    else:
        curve.append(pt)
    state["equity_curve"] = curve
    state["runs"].append({"timestamp":now_iso(),"markets_seen":len(analyzed),"trades_made":len(new_trades),"balance":round(state["balance"],2)})
    save_state(state)
    log.info(f"Ciclo completado. Nuevas ops: {len(new_trades)} | Balance: ${state['balance']:.2f}")
    log.info("="*60)

if __name__ == "__main__":
    run()
