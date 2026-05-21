"""
propagate.py — Mundial 2026
Propaga los datos de un partido a las stats de jugadores y equipos.

Uso:
    python propagate.py <match_file>

Ejemplo:
    python propagate.py ../matches/G1_NZL_vs_IRN.json

Estructura esperada de carpetas:
    mundial-2026/
    ├── teams/          ← NZL.json, SWE.json, etc.
    ├── matches/        ← G1_NZL_vs_IRN.json, etc.
    └── scripts/
        └── propagate.py  ← este archivo
"""

import json
import sys
import os


# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Guardado: {path}")

def get_teams_dir():
    # El script está en scripts/, teams/ está un nivel arriba
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "..", "teams")

def load_team(team_code):
    path = os.path.join(get_teams_dir(), f"{team_code}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se encontró el archivo del equipo: {path}")
    return load_json(path), path

def find_player(team_data, player_id):
    """Devuelve el jugador con ese id dentro del equipo, o None."""
    for player in team_data["players"]:
        if player["id"] == player_id:
            return player
    return None


# ─────────────────────────────────────────────
# LÓGICA DE CLEAN SHEETS
# ─────────────────────────────────────────────

def find_clean_sheet_goalkeeper(lineup, team_data):
    """
    Devuelve el player_id del portero al que asignar la clean sheet.
    Criterio: portero con más minutos jugados.
    En caso de empate exacto (ej. 45/45), se elige al starter.
    """
    goalkeepers = []

    for entry in lineup:
        player = find_player(team_data, entry["player_id"])
        if player and player["position"] == "GK" and entry["minutes_played"] > 0:
            goalkeepers.append({
                "player_id": entry["player_id"],
                "minutes_played": entry["minutes_played"],
                "is_starter": entry["role"] == "starter"
            })

    if not goalkeepers:
        return None

    # Ordenar: primero por minutos (desc), luego starter tiene prioridad en empate
    goalkeepers.sort(key=lambda g: (g["minutes_played"], g["is_starter"]), reverse=True)
    return goalkeepers[0]["player_id"]


# ─────────────────────────────────────────────
# PROPAGACIÓN DE STATS DE JUGADORES
# ─────────────────────────────────────────────

def propagate_player_stats(match, teams):
    """
    Actualiza tournament_stats de cada jugador que aparezca
    en las lineups o events del partido.

    teams es un dict: { "NZL": (team_data, team_path), "IRN": (...), ... }
    """

    # 1. Construir un mapa player_id → team_code para acceso rápido
    player_team_map = {}
    for side in ["home", "away"]:
        team_code = match["home_team"] if side == "home" else match["away_team"]
        for entry in match["lineups"][side]:
            player_team_map[entry["player_id"]] = team_code

    # También mapear jugadores que aparezcan en events pero no en lineups
    # (por si el equipo rival aún no tiene JSON — se ignoran con advertencia)
    for event in match.get("events", []):
        pid = event.get("player_id")
        team_code = event.get("team")
        if pid and team_code and pid not in player_team_map:
            player_team_map[pid] = team_code

    # 2. Determinar clean sheet goalkeepers
    cs_home = match["clean_sheets"]["home"]
    cs_away = match["clean_sheets"]["away"]

    home_code = match["home_team"]
    away_code = match["away_team"]

    cs_gk_home = None
    cs_gk_away = None

    if cs_home and home_code in teams:
        home_data, _ = teams[home_code]
        cs_gk_home = find_clean_sheet_goalkeeper(match["lineups"]["home"], home_data)

    if cs_away and away_code in teams:
        away_data, _ = teams[away_code]
        cs_gk_away = find_clean_sheet_goalkeeper(match["lineups"]["away"], away_data)

    # 3. Contar eventos por jugador
    goals_map = {}
    assists_map = {}
    yellows_map = {}
    reds_map = {}

    for event in match.get("events", []):
        pid = event.get("player_id")
        if not pid:
            continue
        t = event["type"]
        if t == "goal":
            goals_map[pid] = goals_map.get(pid, 0) + 1
        elif t == "assist":
            assists_map[pid] = assists_map.get(pid, 0) + 1
        elif t == "yellow_card":
            yellows_map[pid] = yellows_map.get(pid, 0) + 1
        elif t == "red_card":
            reds_map[pid] = reds_map.get(pid, 0) + 1

    # 4. Construir mapa de ratings
    ratings_map = {}
    for r in match.get("player_ratings", []):
        ratings_map[r["player_id"]] = r["rating"]

    # 5. Actualizar cada jugador en sus lineups
    for side in ["home", "away"]:
        team_code = home_code if side == "home" else away_code

        if team_code not in teams:
            print(f"  ⚠ Equipo {team_code} no encontrado, se omiten sus jugadores.")
            continue

        team_data, _ = teams[team_code]

        for entry in match["lineups"][side]:
            pid = entry["player_id"]
            minutes = entry["minutes_played"]
            role = entry["role"]

            player = find_player(team_data, pid)
            if not player:
                print(f"  ⚠ Jugador {pid} no encontrado en {team_code}.json, se omite.")
                continue

            stats = player["tournament_stats"]

            # Titularidades / banquillo
            if role == "starter":
                stats["started_matches"] = stats.get("started_matches", 0) + 1
            elif role in ("substitute_in", "bench"):
                stats["benched_matches"] = stats.get("benched_matches", 0) + 1

            # Minutos
            stats["minutes_played"] = stats.get("minutes_played", 0) + minutes

            # Solo stats ofensivas/disciplinarias si jugó minutos
            if minutes > 0:
                stats["goals"] = stats.get("goals", 0) + goals_map.get(pid, 0)
                stats["assists"] = stats.get("assists", 0) + assists_map.get(pid, 0)
                stats["yellow_cards"] = stats.get("yellow_cards", 0) + yellows_map.get(pid, 0)
                stats["red_cards"] = stats.get("red_cards", 0) + reds_map.get(pid, 0)

                # Clean sheet solo a porteros
                if player["position"] == "GK":
                    if pid == cs_gk_home or pid == cs_gk_away:
                        stats["clean_sheets"] = stats.get("clean_sheets", 0) + 1

                # Rating — recalcular media
                if pid in ratings_map:
                    new_rating = ratings_map[pid]
                    old_rating = stats.get("rating")
                    # Contar partidos jugados (con minutos) para la media
                    # started_matches + benched donde minutes > 0
                    # Lo más simple: guardar también un contador interno
                    rated_matches = stats.get("_rated_matches", 0) + 1
                    if old_rating is None or old_rating == 6.0 and rated_matches == 1:
                        # Primer partido con nota real
                        stats["rating"] = round(new_rating, 2)
                    else:
                        # Recalcular media acumulada
                        prev_total = old_rating * (rated_matches - 1)
                        stats["rating"] = round((prev_total + new_rating) / rated_matches, 2)
                    stats["_rated_matches"] = rated_matches

            print(f"    · {player['name']} ({pid}) actualizado")

    print()


# ─────────────────────────────────────────────
# PROPAGACIÓN DE STATS DE EQUIPOS
# ─────────────────────────────────────────────

def propagate_team_stats(match, teams):
    """Actualiza tournament_stats del equipo (W/D/L, goles, tarjetas, clean sheets)."""

    home_code = match["home_team"]
    away_code = match["away_team"]
    home_score = match["score"]["home"]
    away_score = match["score"]["away"]

    # Resultado
    if home_score > away_score:
        home_result, away_result = "win", "loss"
    elif home_score < away_score:
        home_result, away_result = "loss", "win"
    else:
        home_result, away_result = "draw", "draw"

    # Contar tarjetas por equipo desde events
    team_yellows = {home_code: 0, away_code: 0}
    team_reds = {home_code: 0, away_code: 0}
    for event in match.get("events", []):
        team = event.get("team")
        if team not in team_yellows:
            continue
        if event["type"] == "yellow_card":
            team_yellows[team] += 1
        elif event["type"] == "red_card":
            team_reds[team] += 1

    for team_code, result, gf, ga, cs in [
        (home_code, home_result, home_score, away_score, match["clean_sheets"]["home"]),
        (away_code, away_result, away_score, home_score, match["clean_sheets"]["away"]),
    ]:
        if team_code not in teams:
            print(f"  ⚠ Equipo {team_code} no encontrado, se omiten sus stats.")
            continue

        team_data, _ = teams[team_code]
        s = team_data["tournament_stats"]

        s["matches_played"] = s.get("matches_played", 0) + 1
        s["goals_for"] = s.get("goals_for", 0) + gf
        s["goals_against"] = s.get("goals_against", 0) + ga
        s["yellow_cards"] = s.get("yellow_cards", 0) + team_yellows.get(team_code, 0)
        s["red_cards"] = s.get("red_cards", 0) + team_reds.get(team_code, 0)

        if result == "win":
            s["wins"] = s.get("wins", 0) + 1
        elif result == "draw":
            s["draws"] = s.get("draws", 0) + 1
        else:
            s["losses"] = s.get("losses", 0) + 1

        if cs:
            s["clean_sheets"] = s.get("clean_sheets", 0) + 1

        print(f"  ✓ Stats de {team_code} actualizadas ({result}, {gf}-{ga})")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python propagate.py <ruta_del_partido>")
        print("Ejemplo: python propagate.py ../matches/G1_NZL_vs_IRN.json")
        sys.exit(1)

    match_path = sys.argv[1]

    if not os.path.exists(match_path):
        print(f"Error: No se encuentra el archivo {match_path}")
        sys.exit(1)

    # Cargar partido
    match = load_json(match_path)
    match_id = match.get("match_id", os.path.basename(match_path))
    print(f"\n{'='*50}")
    print(f"  Propagando: {match_id}")
    print(f"{'='*50}")

    # Comprobar si ya fue propagado
    if match.get("stats_propagated"):
        print("\n⚠ Este partido ya fue propagado (stats_propagated: true).")
        print("  Si quieres repropagar, pon stats_propagated: false en el JSON.")
        sys.exit(0)

    # Cargar los equipos que aparecen en el partido
    home_code = match["home_team"]
    away_code = match["away_team"]
    teams = {}

    for code in [home_code, away_code]:
        try:
            data, path = load_team(code)
            teams[code] = (data, path)
            print(f"  ✓ Cargado: {code}.json")
        except FileNotFoundError as e:
            print(f"  ⚠ {e}")

    print()

    # Propagar stats de jugadores
    print("── Jugadores ──────────────────────────────")
    propagate_player_stats(match, teams)

    # Propagar stats de equipos
    print("── Equipos ────────────────────────────────")
    propagate_team_stats(match, teams)
    print()

    # Guardar los JSONs de equipos actualizados
    print("── Guardando ──────────────────────────────")
    for code, (data, path) in teams.items():
        save_json(path, data)

    # Marcar el partido como propagado y guardarlo
    match["stats_propagated"] = True
    save_json(match_path, match)

    print(f"\n✅ Propagación completada: {match_id}\n")


if __name__ == "__main__":
    main()