from flask import Flask, render_template, request, jsonify
import requests
import math
import time

app = Flask(__name__)

# IMPORTANTE: Reemplaza esto por tu nueva API KEY si la regeneras.
API_KEY = "bf90bbc71e1748aab2fd7fd274ffa5a9"
BASE_URL = "https://api.football-data.org/v4"
headers = {
    "X-Auth-Token": API_KEY
}

# Sistema de Caché en memoria para evitar el límite de 10 llamadas/minuto
CACHE_TIMEOUT = 300  # 5 minutos
matches_cache = {}


def api_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        return response.json()
    except Exception as e:
        return {
            "errors": {
                "local": str(e)
            },
            "response": None
        }


def get_cached_matches(league, season):
    cache_key = f"{league}_{season}"
    now = time.time()
    
    if cache_key in matches_cache:
        timestamp, data = matches_cache[cache_key]
        if now - timestamp < CACHE_TIMEOUT:
            return data
            
    # Si no está en caché o expiró, consultar la API
    params = {}
    if season:
        params["season"] = season
        
    data = api_get(f"/competitions/{league}/matches", params)
    
    # Fallback si el plan gratuito bloquea la temporada (403)
    if data.get("errorCode") == 403 and season:
        data = api_get(f"/competitions/{league}/matches")
        
    if data and "matches" in data:
        matches_cache[cache_key] = (now, data)
        
    return data


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def poisson(goles, media):
    return (math.exp(-media) * pow(media, goles)) / math.factorial(goles)


def process_competition_matches(matches):
    elo = {}  # team_id -> rating
    stats = {}  # team_id -> dict
    
    total_home_goals = 0
    total_away_goals = 0
    completed_matches_count = 0
    
    # Ordenar partidos cronológicamente
    sorted_matches = sorted(matches, key=lambda x: x.get("utcDate", ""))
    
    for match in sorted_matches:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        if not home_team or not away_team or not home_team.get("id") or not away_team.get("id"):
            continue
            
        home_id = int(home_team.get("id"))
        away_id = int(away_team.get("id"))
        
        # Inicializar ELO si no existe
        if home_id not in elo: elo[home_id] = 1500.0
        if away_id not in elo: elo[away_id] = 1500.0
        
        # Inicializar estadísticas
        for tid in [home_id, away_id]:
            if tid not in stats:
                is_home = (tid == home_id)
                stats[tid] = {
                    "name": home_team.get("name") if is_home else away_team.get("name"),
                    "crest": home_team.get("crest") if is_home else away_team.get("crest"),
                    "home_played": 0, "home_won": 0, "home_draw": 0, "home_lost": 0, "home_goals_for": 0, "home_goals_against": 0,
                    "away_played": 0, "away_won": 0, "away_draw": 0, "away_lost": 0, "away_goals_for": 0, "away_goals_against": 0,
                    "recent": []  # List of tuples: (goals_scored, goals_conceded, 'W'/'D'/'L')
                }
        
        status = match.get("status")
        if status == "FINISHED":
            score = match.get("score", {})
            full_time = score.get("fullTime", {})
            hg = full_time.get("home")
            ag = full_time.get("away")
            
            if hg is None or ag is None:
                continue
                
            hg = int(hg)
            ag = int(ag)
            
            completed_matches_count += 1
            total_home_goals += hg
            total_away_goals += ag
            
            # Registrar estadísticas
            stats[home_id]["home_played"] += 1
            stats[home_id]["home_goals_for"] += hg
            stats[home_id]["home_goals_against"] += ag
            
            stats[away_id]["away_played"] += 1
            stats[away_id]["away_goals_for"] += ag
            stats[away_id]["away_goals_against"] += hg
            
            # Determinar resultado y actualizar rachas
            if hg > ag:
                stats[home_id]["home_won"] += 1
                stats[away_id]["away_lost"] += 1
                hr, ar = 1.0, 0.0
                stats[home_id]["recent"].append((hg, ag, "W"))
                stats[away_id]["recent"].append((ag, hg, "L"))
            elif hg == ag:
                stats[home_id]["home_draw"] += 1
                stats[away_id]["away_draw"] += 1
                hr, ar = 0.5, 0.5
                stats[home_id]["recent"].append((hg, ag, "D"))
                stats[away_id]["recent"].append((ag, hg, "D"))
            else:
                stats[home_id]["home_lost"] += 1
                stats[away_id]["away_won"] += 1
                hr, ar = 0.0, 1.0
                stats[home_id]["recent"].append((hg, ag, "L"))
                stats[away_id]["recent"].append((ag, hg, "W"))
                
            # Actualizar ELO
            r_home = elo[home_id]
            r_away = elo[away_id]
            
            e_home = 1.0 / (1.0 + 10.0 ** ((r_away - r_home) / 400.0))
            e_away = 1.0 - e_home
            
            k = 32.0
            # Multiplicador por margen de victoria (aporta más realismo)
            goal_diff = abs(hg - ag)
            if goal_diff >= 2:
                if goal_diff == 2:
                    k *= 1.5
                elif goal_diff == 3:
                    k *= 1.75
                else:
                    k *= 1.75 + (goal_diff - 3) / 8.0
                    
            elo[home_id] += k * (hr - e_home)
            elo[away_id] += k * (ar - e_away)
            
    avg_home_goals = total_home_goals / completed_matches_count if completed_matches_count > 0 else 1.35
    avg_away_goals = total_away_goals / completed_matches_count if completed_matches_count > 0 else 1.05
    
    return elo, stats, avg_home_goals, avg_away_goals


def get_recent_averages(recent_list, default_scored, default_conceded):
    if not recent_list:
        return default_scored, default_conceded
        
    # Ponderar los últimos 5 partidos con decaimiento lineal (pesos: 10, 9, 8, 7, 6)
    last_5 = recent_list[-5:]
    weights = [10, 9, 8, 7, 6][:len(last_5)]
    sum_weights = sum(weights)
    
    weighted_scored = sum(last_5[-i][0] * weights[i-1] for i in range(1, len(last_5) + 1))
    weighted_conceded = sum(last_5[-i][1] * weights[i-1] for i in range(1, len(last_5) + 1))
    
    return weighted_scored / sum_weights, weighted_conceded / sum_weights


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/teams-by-league")
def teams_by_league():
    league = request.args.get("league")
    season = request.args.get("season")

    if not league:
        return jsonify({"error": "Falta seleccionar torneo"}), 400

    data = get_cached_matches(league, season)
    
    if not data or "matches" not in data:
        # Fallback si hay algún error con la consulta de partidos
        return jsonify({
            "error": "Error al consultar los partidos en la API",
            "message": data.get("message", "No se recibieron partidos de la API.")
        }), 400

    # Construir listado único de equipos
    teams_map = {}
    for match in data.get("matches", []):
        for side in ["homeTeam", "awayTeam"]:
            team = match.get(side, {})
            if team.get("id") and team.get("name"):
                teams_map[team["id"]] = {
                    "id": team["id"],
                    "name": team["name"],
                    "crest": team.get("crest", "")
                }
                
    teams_list = sorted(list(teams_map.values()), key=lambda x: x["name"])
    return jsonify({"teams": teams_list})


@app.route("/api/custom-prediction")
def custom_prediction():
    league = request.args.get("league")
    season = request.args.get("season")

    home_id = request.args.get("home")
    away_id = request.args.get("away")

    if not league or not home_id or not away_id:
        return jsonify({
            "error": "Falta torneo, equipo local o equipo visitante"
        }), 400

    if home_id == away_id:
        return jsonify({
            "error": "No puedes seleccionar el mismo equipo dos veces."
        }), 400

    home_id = int(home_id)
    away_id = int(away_id)

    # Obtener los partidos (usando la caché)
    data = get_cached_matches(league, season)
    
    if not data or "matches" not in data:
        return jsonify({
            "error": "Error consultando los partidos del torneo"
        }), 400

    elo, stats, avg_home_goals, avg_away_goals = process_competition_matches(data.get("matches", []))

    if home_id not in stats or away_id not in stats:
        return jsonify({
            "error": "No hay estadísticas suficientes para estos equipos."
        }), 400

    h_stats = stats[home_id]
    a_stats = stats[away_id]

    # ELO de cada equipo
    home_elo = elo.get(home_id, 1500.0)
    away_elo = elo.get(away_id, 1500.0)

    # 1. Fuerza de la Temporada Completa
    h_played_home = h_stats["home_played"]
    a_played_away = a_stats["away_played"]

    # Promedio de goles marcados/recibidos en casa por el local
    home_season_att = h_stats["home_goals_for"] / h_played_home if h_played_home > 0 else avg_home_goals
    home_season_def = h_stats["home_goals_against"] / h_played_home if h_played_home > 0 else avg_away_goals

    # Promedio de goles marcados/recibidos fuera por el visitante
    away_season_att = a_stats["away_goals_for"] / a_played_away if a_played_away > 0 else avg_away_goals
    away_season_def = a_stats["away_goals_against"] / a_played_away if a_played_away > 0 else avg_home_goals

    # 2. Promedio de Goles de Racha Reciente (Últimos 5 partidos con pesos decrecientes)
    home_recent_att, home_recent_def = get_recent_averages(h_stats["recent"], home_season_att, home_season_def)
    away_recent_att, away_recent_def = get_recent_averages(a_stats["recent"], away_season_att, away_season_def)

    # Mezcla: 40% datos de la temporada completa + 60% racha reciente
    home_att = (home_season_att * 0.40) + (home_recent_att * 0.60)
    home_def = (home_season_def * 0.40) + (home_recent_def * 0.60)
    away_att = (away_season_att * 0.40) + (away_recent_att * 0.60)
    away_def = (away_season_def * 0.40) + (away_recent_def * 0.60)

    # Calcular fuerza defensiva y ofensiva respecto a las medias de la liga
    has = home_att / avg_home_goals if avg_home_goals > 0 else 1.0
    hds = home_def / avg_away_goals if avg_away_goals > 0 else 1.0
    aas = away_att / avg_away_goals if avg_away_goals > 0 else 1.0
    ads = away_def / avg_home_goals if avg_home_goals > 0 else 1.0

    # 3. Goles Esperados Base (Poisson)
    exp_home_goals = has * ads * avg_home_goals
    exp_away_goals = aas * hds * avg_away_goals

    # 4. Ajustar goles esperados según factor de diferencia ELO
    elo_diff = home_elo - away_elo
    # 100 puntos de ELO equivalen a un ajuste aproximado de 10% en el xG del equipo
    home_elo_adj = 1.0 + (elo_diff / 1000.0)
    away_elo_adj = 1.0 - (elo_diff / 1000.0)

    exp_home_goals = max(0.05, exp_home_goals * home_elo_adj)
    exp_away_goals = max(0.05, exp_away_goals * away_elo_adj)

    # Aplicar ventaja de localía adicional (+10% / -10%) solo si NO es un torneo neutral
    if league not in ["WC", "EC"]:
        exp_home_goals = exp_home_goals * 1.10
        exp_away_goals = exp_away_goals * 0.90

    # 5. Generar Matriz de Distribución de Poisson (de 0-0 a 5-5)
    prob_home_win = 0
    prob_draw = 0
    prob_away_win = 0
    prob_over_25 = 0
    prob_under_25 = 0
    prob_btts_yes = 0

    score_probs = []
    matrix_max = 5

    # Para normalizar las probabilidades dentro del espacio 0-0 a 5-5
    sum_total_matrix = 0.0

    for i in range(matrix_max + 1):
        for j in range(matrix_max + 1):
            p = poisson(i, exp_home_goals) * poisson(j, exp_away_goals)
            sum_total_matrix += p

            if i > j:
                prob_home_win += p
            elif i == j:
                prob_draw += p
            else:
                prob_away_win += p

            if i + j > 2.5:
                prob_over_25 += p
            else:
                prob_under_25 += p

            if i > 0 and j > 0:
                prob_btts_yes += p

            score_probs.append({
                "score": f"{i}-{j}",
                "probability": p
            })

    # Normalizar para compensar puntuaciones fuera de la matriz 5x5
    if sum_total_matrix > 0:
        prob_home_win /= sum_total_matrix
        prob_draw /= sum_total_matrix
        prob_away_win /= sum_total_matrix
        prob_over_25 /= sum_total_matrix
        prob_under_25 /= sum_total_matrix
        prob_btts_yes /= sum_total_matrix
        for item in score_probs:
            item["probability"] /= sum_total_matrix

    prob_btts_no = 1.0 - prob_btts_yes

    # Double Chance
    prob_dc_1x = prob_home_win + prob_draw
    prob_dc_x2 = prob_away_win + prob_draw
    prob_dc_12 = prob_home_win + prob_away_win

    # Marcadores más probables
    score_probs = sorted(
        score_probs,
        key=lambda x: x["probability"],
        reverse=True
    )[:5]

    # 6. Generar Índice de Confianza
    # Basado en partidos jugados, diferencia de ELO y consistencia de racha
    home_played_total = h_stats["home_played"] + h_stats["away_played"]
    away_played_total = a_stats["home_played"] + a_stats["away_played"]
    
    played_factor = min(1.0, (home_played_total + away_played_total) / 20.0) * 45.0  # Peso: 45%
    elo_factor = min(1.0, abs(elo_diff) / 300.0) * 30.0  # Peso: 30%
    
    # Factor de cantidad de datos de racha (máximo 5 partidos por equipo)
    form_len = len(h_stats["recent"]) + len(a_stats["recent"])
    form_factor = min(1.0, form_len / 10.0) * 25.0  # Peso: 25%
    
    confidence_score = round(played_factor + elo_factor + form_factor, 1)
    # Rango final restringido a límites realistas
    confidence_score = max(40.0, min(95.0, confidence_score))

    if confidence_score >= 75.0:
        confidence_lbl = "Alta"
    elif confidence_score >= 55.0:
        confidence_lbl = "Media"
    else:
        confidence_lbl = "Baja"

    # Determinar recomendación
    probs_dict = {
        "home_win": prob_home_win,
        "draw": prob_draw,
        "away_win": prob_away_win,
        "over_25": prob_over_25,
        "under_25": prob_under_25,
        "btts_yes": prob_btts_yes,
        "btts_no": prob_btts_no
    }

    labels = {
        "home_win": f"Gana {h_stats['name']}",
        "draw": "Empate",
        "away_win": f"Gana {a_stats['name']}",
        "over_25": "Más de 2.5 goles",
        "under_25": "Menos de 2.5 goles",
        "btts_yes": "Ambos anotan: Sí",
        "btts_no": "Ambos anotan: No"
    }

    best_market = max(probs_dict, key=probs_dict.get)

    # Racha reciente formateada para lectura (ej. W-D-L)
    home_form_str = "-".join([item[2] for item in h_stats["recent"][-5:]])
    away_form_str = "-".join([item[2] for item in a_stats["recent"][-5:]])

    result = {
        "match": f"{h_stats['name']} vs {a_stats['name']}",
        "season": season,
        "expected_goals": {
            "home": round(exp_home_goals, 2),
            "away": round(exp_away_goals, 2)
        },
        "home_stats": {
            "played": int(home_played_total),
            "won": h_stats["home_won"] + h_stats["away_won"],
            "draw": h_stats["home_draw"] + h_stats["away_draw"],
            "lost": h_stats["home_lost"] + h_stats["away_lost"],
            "goals_for": int(h_stats["home_goals_for"] + h_stats["away_goals_for"]),
            "goals_against": int(h_stats["home_goals_against"] + h_stats["away_goals_against"]),
            "avg_for": round(home_att, 2),
            "avg_against": round(home_def, 2),
            "form": home_form_str,
            "crest": h_stats["crest"],
            "elo": round(home_elo)
        },
        "away_stats": {
            "played": int(away_played_total),
            "won": a_stats["home_won"] + a_stats["away_won"],
            "draw": a_stats["home_draw"] + a_stats["away_draw"],
            "lost": a_stats["home_lost"] + a_stats["away_lost"],
            "goals_for": int(a_stats["home_goals_for"] + a_stats["away_goals_for"]),
            "goals_against": int(a_stats["home_goals_against"] + a_stats["away_goals_against"]),
            "avg_for": round(away_att, 2),
            "avg_against": round(away_def, 2),
            "form": away_form_str,
            "crest": a_stats["crest"],
            "elo": round(away_elo)
        },
        "probabilities": {
            "home_win": round(prob_home_win * 100, 2),
            "draw": round(prob_draw * 100, 2),
            "away_win": round(prob_away_win * 100, 2),
            "over_25": round(prob_over_25 * 100, 2),
            "under_25": round(prob_under_25 * 100, 2),
            "btts_yes": round(prob_btts_yes * 100, 2),
            "btts_no": round(prob_btts_no * 100, 2),
            "dc_1x": round(prob_dc_1x * 100, 2),
            "dc_x2": round(prob_dc_x2 * 100, 2),
            "dc_12": round(prob_dc_12 * 100, 2)
        },
        "top_scores": [
            {
                "score": item["score"],
                "probability": round(item["probability"] * 100, 2)
            }
            for item in score_probs
        ],
        "recommendation": {
            "market": labels[best_market],
            "probability": round(probs_dict[best_market] * 100, 2),
            "confidence": confidence_lbl,
            "confidence_val": confidence_score
        }
    }

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)