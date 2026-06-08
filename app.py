from flask import Flask, render_template, request, jsonify
import requests
import math

app = Flask(__name__)

# IMPORTANTE:
# Reemplaza esto por tu nueva API KEY.
API_KEY = "bf90bbc71e1748aab2fd7fd274ffa5a9"

BASE_URL = "https://api.football-data.org/v4"

headers = {
    "X-Auth-Token": API_KEY
}


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


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def poisson(goles, media):
    return (math.exp(-media) * pow(media, goles)) / math.factorial(goles)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/teams-by-league")
def teams_by_league():
    league = request.args.get("league")
    season = request.args.get("season")

    if not league:
        return jsonify({"error": "Falta seleccionar torneo"}), 400

    params = {}
    if season:
        params["season"] = season

    data = api_get(f"/competitions/{league}/teams", params)

    # Fallback si da 403 por plan gratuito al consultar temporadas pasadas/futuras
    if data.get("errorCode") == 403 and season:
        data = api_get(f"/competitions/{league}/teams")

    return jsonify(data)


@app.route("/api/custom-prediction")
def custom_prediction():
    league = request.args.get("league")
    season = request.args.get("season")

    home_id = request.args.get("home")
    away_id = request.args.get("away")

    home_name = request.args.get("home_name", "Equipo 1")
    away_name = request.args.get("away_name", "Equipo 2")

    if not league or not home_id or not away_id:
        return jsonify({
            "error": "Falta torneo, equipo local o equipo visitante"
        }), 400

    if home_id == away_id:
        return jsonify({
            "error": "No puedes seleccionar el mismo equipo dos veces."
        }), 400

    params = {}
    if season:
        params["season"] = season

    # Fetch standings of the competition to get team stats in 1 API call
    standings_data = api_get(f"/competitions/{league}/standings", params)

    # Fallback si da 403 por plan gratuito
    if standings_data.get("errorCode") == 403 and season:
        standings_data = api_get(f"/competitions/{league}/standings")

    if standings_data.get("errors") or "standings" not in standings_data:
        # Check if the API returned an explicit error message
        err_msg = standings_data.get("message")
        if not err_msg and standings_data.get("errors"):
            err_msg = str(standings_data.get("errors"))
        return jsonify({
            "error": "Error consultando la tabla de posiciones del torneo",
            "detalle": err_msg or "Verifica que el torneo y la temporada sean correctos para tu plan."
        }), 400

    standings = standings_data.get("standings", [])
    
    home_stats = None
    away_stats = None

    # Loop through groups/tables to find the home and away teams
    for standing in standings:
        table = standing.get("table", [])
        for row in table:
            team_id = str(row.get("team", {}).get("id"))
            if team_id == str(home_id):
                home_stats = row
            if team_id == str(away_id):
                away_stats = row

    # Fallback defaults if no statistics exist yet (e.g. before World Cup starts)
    # or if the team was not found in the standings
    default_played = 0
    default_goals_for = 0
    default_goals_against = 0

    home_played = safe_float(home_stats.get("playedGames") if home_stats else default_played)
    home_goals_for = safe_float(home_stats.get("goalsFor") if home_stats else default_goals_for)
    home_goals_against = safe_float(home_stats.get("goalsAgainst") if home_stats else default_goals_against)

    away_played = safe_float(away_stats.get("playedGames") if away_stats else default_played)
    away_goals_for = safe_float(away_stats.get("goalsFor") if away_stats else default_goals_for)
    away_goals_against = safe_float(away_stats.get("goalsAgainst") if away_stats else default_goals_against)

    # Calculate average goals. 
    # Fallback to 1.2 goals expected per match if no games have been played.
    if home_played > 0:
        home_attack = home_goals_for / home_played
        home_defense = home_goals_against / home_played
    else:
        home_attack = 1.2
        home_defense = 1.2

    if away_played > 0:
        away_attack = away_goals_for / away_played
        away_defense = away_goals_against / away_played
    else:
        away_attack = 1.2
        away_defense = 1.2

    # Goles esperados
    exp_home_goals = max((home_attack + away_defense) / 2, 0.05)
    exp_away_goals = max((away_attack + home_defense) / 2, 0.05)

    prob_home_win = 0
    prob_draw = 0
    prob_away_win = 0
    prob_over_25 = 0
    prob_under_25 = 0
    prob_btts_yes = 0

    score_probs = []

    max_goals = 10

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = poisson(i, exp_home_goals) * poisson(j, exp_away_goals)

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

    prob_btts_no = 1 - prob_btts_yes

    score_probs = sorted(
        score_probs,
        key=lambda x: x["probability"],
        reverse=True
    )[:5]

    probs = {
        "home_win": prob_home_win,
        "draw": prob_draw,
        "away_win": prob_away_win,
        "over_25": prob_over_25,
        "under_25": prob_under_25,
        "btts_yes": prob_btts_yes,
        "btts_no": prob_btts_no
    }

    labels = {
        "home_win": f"Gana {home_name}",
        "draw": "Empate",
        "away_win": f"Gana {away_name}",
        "over_25": "Más de 2.5 goles",
        "under_25": "Menos de 2.5 goles",
        "btts_yes": "Ambos anotan: Sí",
        "btts_no": "Ambos anotan: No"
    }

    best_market = max(probs, key=probs.get)

    confidence = "Baja"

    if probs[best_market] >= 0.65:
        confidence = "Alta"
    elif probs[best_market] >= 0.55:
        confidence = "Media"

    result = {
        "match": f"{home_name} vs {away_name}",
        "season": season,
        "expected_goals": {
            "home": round(exp_home_goals, 2),
            "away": round(exp_away_goals, 2)
        },
        "probabilities": {
            "home_win": round(prob_home_win * 100, 2),
            "draw": round(prob_draw * 100, 2),
            "away_win": round(prob_away_win * 100, 2),
            "over_25": round(prob_over_25 * 100, 2),
            "under_25": round(prob_under_25 * 100, 2),
            "btts_yes": round(prob_btts_yes * 100, 2),
            "btts_no": round(prob_btts_no * 100, 2)
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
            "probability": round(probs[best_market] * 100, 2),
            "confidence": confidence
        }
    }

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)