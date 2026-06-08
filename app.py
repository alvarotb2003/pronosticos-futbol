from flask import Flask, render_template, request, jsonify
import requests
import math
import time
import json
import os

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

ELO_DB_FILE = os.path.join(os.path.dirname(__file__), "elo_database.json")

def load_elo_database():
    if os.path.exists(ELO_DB_FILE):
        try:
            with open(ELO_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_matches": [], "ratings": {}}

def save_elo_database(db):
    try:
        with open(ELO_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

# ELO Baselines estimadas para selecciones y clubes populares
ELO_BASELINES = {
    # Selecciones Nacionales
    "Argentina": 1820.0,
    "Brazil": 1780.0,
    "France": 1800.0,
    "England": 1770.0,
    "Spain": 1790.0,
    "Portugal": 1750.0,
    "Germany": 1730.0,
    "Netherlands": 1740.0,
    "Italy": 1720.0,
    "Uruguay": 1725.0,
    "Belgium": 1700.0,
    "Croatia": 1690.0,
    "Colombia": 1715.0,
    "Mexico": 1580.0,
    "USA": 1600.0,
    "Morocco": 1650.0,
    "Senegal": 1610.0,
    "Japan": 1640.0,
    # Clubes Importantes
    "Manchester City FC": 1860.0,
    "Real Madrid CF": 1870.0,
    "FC Bayern München": 1830.0,
    "Arsenal FC": 1820.0,
    "FC Barcelona": 1810.0,
    "Liverpool FC": 1840.0,
    "Paris Saint-Germain FC": 1790.0,
    "FC Internazionale Milano": 1820.0,
    "Juventus FC": 1760.0,
    "Bayer 04 Leverkusen": 1810.0,
    "Borussia Dortmund": 1780.0,
    "Atlético Madrid": 1775.0,
}

def get_baseline_elo(team_name):
    if not team_name:
        return 1500.0
    for name, rating in ELO_BASELINES.items():
        if name in team_name or team_name in name:
            return rating
    return 1500.0


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


def get_cached_matches(league, season=None):
    cache_key = f"{league}_{season}" if season else league
    now = time.time()
    
    if cache_key in matches_cache:
        timestamp, data = matches_cache[cache_key]
        if now - timestamp < CACHE_TIMEOUT:
            return data
            
    # Consultar la API de partidos, pasando la temporada si está presente
    params = {"season": season} if season else None
    data = api_get(f"/competitions/{league}/matches", params=params)
        
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
    elo_db = load_elo_database()
    processed_matches = set(elo_db.get("processed_matches", []))
    ratings = elo_db.get("ratings", {})
    
    elo = {}  # team_id -> rating
    stats = {}  # team_id -> dict
    
    total_home_goals = 0
    total_away_goals = 0
    completed_matches_count = 0
    
    # Ordenar partidos cronológicamente
    sorted_matches = sorted(matches, key=lambda x: x.get("utcDate", ""))
    
    # Pre-cargar ELOs e inicializar objetos
    for match in sorted_matches:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        if not home_team or not away_team or not home_team.get("id") or not away_team.get("id"):
            continue
            
        home_id = str(home_team.get("id"))
        away_id = str(away_team.get("id"))
        
        if home_id not in elo:
            elo[int(home_id)] = float(ratings.get(home_id, get_baseline_elo(home_team.get("name", ""))))
        if away_id not in elo:
            elo[int(away_id)] = float(ratings.get(away_id, get_baseline_elo(away_team.get("name", ""))))
            
        home_id_int = int(home_id)
        away_id_int = int(away_id)
        
        for tid, t_obj in [(home_id_int, home_team), (away_id_int, away_team)]:
            if tid not in stats:
                stats[tid] = {
                    "name": t_obj.get("name"),
                    "crest": t_obj.get("crest"),
                    "home_played": 0, "home_won": 0, "home_draw": 0, "home_lost": 0, "home_goals_for": 0, "home_goals_against": 0,
                    "away_played": 0, "away_won": 0, "away_draw": 0, "away_lost": 0, "away_goals_for": 0, "away_goals_against": 0,
                    "recent": []  # List of tuples: (goals_scored, goals_conceded, 'W'/'D'/'L')
                }
                
    db_updated = False
    
    for match in sorted_matches:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        if not home_team or not away_team or not home_team.get("id") or not away_team.get("id"):
            continue
            
        home_id = int(home_team.get("id"))
        away_id = int(away_team.get("id"))
        match_id = match.get("id")
        
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
            goal_diff = abs(hg - ag)
            if goal_diff >= 2:
                if goal_diff == 2:
                    k *= 1.5
                elif goal_diff == 3:
                    k *= 1.75
                else:
                    k *= 1.75 + (goal_diff - 3) / 8.0
                    
            delta_home = k * (hr - e_home)
            delta_away = k * (ar - e_away)
            
            elo[home_id] += delta_home
            elo[away_id] += delta_away
            
            # Solo actualizar la DB persistente si este partido NO se procesó antes
            if match_id and match_id not in processed_matches:
                ratings[str(home_id)] = elo[home_id]
                ratings[str(away_id)] = elo[away_id]
                processed_matches.add(match_id)
                db_updated = True
                
    if db_updated:
        elo_db["processed_matches"] = list(processed_matches)
        elo_db["ratings"] = ratings
        save_elo_database(elo_db)
            
    avg_home_goals = total_home_goals / completed_matches_count if completed_matches_count > 0 else 1.35
    avg_away_goals = total_away_goals / completed_matches_count if completed_matches_count > 0 else 1.05
    
    return elo, stats, avg_home_goals, avg_away_goals


def get_recent_averages(recent_list, default_scored, default_conceded):
    if not recent_list:
        return default_scored, default_conceded
        
    # Ponderar los últimos 10 partidos con decaimiento lineal (pesos: 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
    last_10 = recent_list[-10:]
    weights = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1][:len(last_10)]
    sum_weights = sum(weights)
    
    weighted_scored = sum(last_10[-i][0] * weights[i-1] for i in range(1, len(last_10) + 1))
    weighted_conceded = sum(last_10[-i][1] * weights[i-1] for i in range(1, len(last_10) + 1))
    
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

    home_name_arg = request.args.get("home_name", f"Equipo {home_id}")
    away_name_arg = request.args.get("away_name", f"Equipo {away_id}")

    if home_id not in stats:
        stats[home_id] = {
            "name": home_name_arg,
            "crest": "",
            "home_played": 0, "home_won": 0, "home_draw": 0, "home_lost": 0, "home_goals_for": 0, "home_goals_against": 0,
            "away_played": 0, "away_won": 0, "away_draw": 0, "away_lost": 0, "away_goals_for": 0, "away_goals_against": 0,
            "recent": []
        }
        
    if away_id not in stats:
        stats[away_id] = {
            "name": away_name_arg,
            "crest": "",
            "home_played": 0, "home_won": 0, "home_draw": 0, "home_lost": 0, "home_goals_for": 0, "home_goals_against": 0,
            "away_played": 0, "away_won": 0, "away_draw": 0, "away_lost": 0, "away_goals_for": 0, "away_goals_against": 0,
            "recent": []
        }

    h_stats = stats[home_id]
    a_stats = stats[away_id]

    home_played_total = h_stats["home_played"] + h_stats["away_played"]
    away_played_total = a_stats["home_played"] + a_stats["away_played"]

    # Determinar Calidad de Datos
    min_played = min(home_played_total, away_played_total)
    if min_played >= 8:
        data_quality = "Excelente"
    elif min_played >= 5:
        data_quality = "Buena"
    elif min_played >= 3:
        data_quality = "Limitada"
    else:
        data_quality = "Estimada (Basada en ELO)"

    # ELO de cada equipo
    home_elo = elo.get(home_id, 1500.0)
    away_elo = elo.get(away_id, 1500.0)

    # 1. Fuerza de la Temporada Completa
    h_played_home = h_stats["home_played"]
    a_played_away = a_stats["away_played"]

    home_season_att = h_stats["home_goals_for"] / h_played_home if h_played_home > 0 else avg_home_goals
    home_season_def = h_stats["home_goals_against"] / h_played_home if h_played_home > 0 else avg_away_goals

    away_season_att = a_stats["away_goals_for"] / a_played_away if a_played_away > 0 else avg_away_goals
    away_season_def = a_stats["away_goals_against"] / a_played_away if a_played_away > 0 else avg_home_goals

    # 2. Promedio de Goles de Racha Reciente (Últimos 10 partidos con pesos decrecientes)
    home_recent_att, home_recent_def = get_recent_averages(h_stats["recent"], home_season_att, home_season_def)
    away_recent_att, away_recent_def = get_recent_averages(a_stats["recent"], away_season_att, away_season_def)

    # Mezcla: 30% datos de la temporada completa + 70% racha reciente
    home_att = (home_season_att * 0.30) + (home_recent_att * 0.70)
    home_def = (home_season_def * 0.30) + (home_recent_def * 0.70)
    away_att = (away_season_att * 0.30) + (away_recent_att * 0.70)
    away_def = (away_season_def * 0.30) + (away_recent_def * 0.70)

    # Calcular fuerza defensiva y ofensiva respecto a las medias de la liga
    has = home_att / avg_home_goals if avg_home_goals > 0 else 1.0
    hds = home_def / avg_away_goals if avg_away_goals > 0 else 1.0
    aas = away_att / avg_away_goals if avg_away_goals > 0 else 1.0
    ads = away_def / avg_home_goals if avg_home_goals > 0 else 1.0

    # 3. Goles Esperados Base
    exp_home_goals = has * ads * avg_home_goals
    exp_away_goals = aas * hds * avg_away_goals

    # 4. Ajustar goles esperados según factor de diferencia ELO (Escala de 400 puntos)
    elo_diff = home_elo - away_elo
    home_elo_adj = max(0.15, min(2.5, 1.0 + (elo_diff / 400.0)))
    away_elo_adj = max(0.15, min(2.5, 1.0 - (elo_diff / 400.0)))

    exp_home_goals = max(0.05, exp_home_goals * home_elo_adj)
    exp_away_goals = max(0.05, exp_away_goals * away_elo_adj)

    # Aplicar ventaja de localía adicional (+10% / -10%) solo si NO es un torneo neutral
    if league not in ["WC", "EC"]:
        exp_home_goals = exp_home_goals * 1.10
        exp_away_goals = exp_away_goals * 0.90

    # 5. Generar Matriz de Distribución de Poisson Ampliada (de 0-0 a 8-8)
    prob_home_win = 0
    prob_draw = 0
    prob_away_win = 0
    prob_over_25 = 0
    prob_under_25 = 0
    prob_btts_yes = 0

    score_probs = []
    matrix_max = 8  # Matriz de 8x8 para mayor realismo estadístico

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

    # Normalizar para compensar puntuaciones fuera de la matriz 8x8
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
    played_factor = min(1.0, (home_played_total + away_played_total) / 20.0) * 45.0  # Peso: 45%
    elo_factor = min(1.0, abs(elo_diff) / 300.0) * 30.0  # Peso: 30%
    
    # Factor de cantidad de datos de racha (máximo 10 partidos por equipo)
    form_len = len(h_stats["recent"]) + len(a_stats["recent"])
    form_factor = min(1.0, form_len / 20.0) * 25.0  # Peso: 25%
    
    confidence_score = round(played_factor + elo_factor + form_factor, 1)

    # Reglas especiales de confianza basadas en partidos reales
    if home_played_total < 5 or away_played_total < 5:
        confidence_lbl = "Muy Baja"
        confidence_score = min(45.0, confidence_score)
    else:
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

    # Racha reciente formateada para lectura (últimos 10 partidos)
    home_form_str = "-".join([item[2] for item in h_stats["recent"][-10:]])
    away_form_str = "-".join([item[2] for item in a_stats["recent"][-10:]])

    result = {
        "insufficient_data": False,
        "data_quality": data_quality,
        "match": f"{h_stats['name']} vs {a_stats['name']}",
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