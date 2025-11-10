from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from time import sleep
from datetime import datetime, timedelta
import asyncio
import aiohttp
from collections import defaultdict
from psycopg2.extras import execute_values
import psycopg2
from sqlalchemy.schema import UniqueConstraint
import boto3
import json
import traceback
from botocore.exceptions import ClientError

# Explicitly specify the .env file path to ensure it's loaded correctly
load_dotenv(dotenv_path=".env")

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Riot API key (Reminder: Store this in a .env file for security!)
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "RGAPI-ab034026-0b86-4bc1-9d26-90762153f017")

# AWS Bedrock Model ID
BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Debugging: Print the loaded API key (masked) to verify it's being loaded correctly
print(f"Loaded API Key: {RIOT_API_KEY[:8]}...masked")

# Add database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Update database configuration to include connection health checks
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,  # Check if connections are alive before using them
    'pool_recycle': 1800  # Recycle connections every 30 minutes
}

# Initialize SQLAlchemy and Flask-Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Initialize AWS Bedrock client
try:
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    print("AWS Bedrock client initialized successfully")
except Exception as e:
    print(f"Warning: Failed to initialize AWS Bedrock client: {e}")
    bedrock = None

# Updated Match model with analytics-ready schema
class Match(db.Model):
    id = db.Column(db.String, primary_key=True)
    game_mode = db.Column(db.String, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    win = db.Column(db.Boolean, nullable=False)
    timestamp = db.Column(db.BigInteger, nullable=False, index=True)

    # Identity
    role = db.Column(db.String, nullable=False)
    champion = db.Column(db.String, nullable=False)
    puuid = db.Column(db.String, nullable=False)

    # Core Combat Stats
    kills = db.Column(db.Integer, nullable=False)
    deaths = db.Column(db.Integer, nullable=False)
    assists = db.Column(db.Integer, nullable=False)
    damage = db.Column(db.Integer, nullable=False)  # totalDamageDealtToChampions
    damage_taken = db.Column(db.Integer, nullable=False)  # totalDamageTaken
    time_dead = db.Column(db.Integer, nullable=False)  # totalTimeSpentDead

    # Economy
    gold = db.Column(db.Integer, nullable=False)  # goldEarned

    # Farming
    cs = db.Column(db.Integer, nullable=False)  # totalMinionsKilled
    neutral_cs = db.Column(db.Integer, nullable=False)  # neutralMinionsKilled
    enemy_jungle_cs = db.Column(db.Integer, nullable=False)  # totalEnemyJungleMinionsKilled
    ally_jungle_cs = db.Column(db.Integer, nullable=False)  # totalAllyJungleMinionsKilled

    # Vision
    vision = db.Column(db.Integer, nullable=False)  # visionScore
    wards_placed = db.Column(db.Integer, nullable=False)
    wards_killed = db.Column(db.Integer, nullable=False)

    # Objectives
    dragons = db.Column(db.Integer, nullable=False)
    barons = db.Column(db.Integer, nullable=False)
    heralds = db.Column(db.Integer, nullable=False)
    towers = db.Column(db.Integer, nullable=False)
    inhibitors = db.Column(db.Integer, nullable=False)

    # Team Totals (computed)
    team_kills = db.Column(db.Integer, nullable=False)
    team_damage = db.Column(db.Integer, nullable=False)
    team_gold = db.Column(db.Integer, nullable=False)
    team_vision = db.Column(db.Integer, nullable=False)

# New MatchTimelineSummary model for aggregated timeline insights
class MatchTimelineSummary(db.Model):
    __tablename__ = "match_timeline_summary"

    match_id = db.Column(db.String, primary_key=True)
    puuid = db.Column(db.String, primary_key=True)

    early_dominance_score = db.Column(db.Float)
    midgame_swing_score = db.Column(db.Float)
    consistency_score = db.Column(db.Float)

    level_6_timestamp = db.Column(db.Integer)
    level_11_timestamp = db.Column(db.Integer)
    level_16_timestamp = db.Column(db.Integer)

    biggest_spike = db.Column(db.Float)
    biggest_throw = db.Column(db.Float)

    roam_score = db.Column(db.Float)

    kill_positions = db.Column(db.JSON)
    objective_presence = db.Column(db.JSON)

    comeback_type = db.Column(db.String)
    duration = db.Column(db.Integer)

# Add other models as needed

# Root endpoint
@app.route("/")
def home():
    """Returns a status message indicating the backend is online."""
    return jsonify({"status": "Rift Rewind Backend Online"})

# Helper to reset database connection
def reset_db_connection():
    db.session.remove()
    db.engine.dispose()

# New helper function to fetch active region from Riot API
async def get_active_region(session, puuid):
    """Fetch the active region for a given PUUID using Riot's region endpoint."""
    try:
        region_url = f"https://americas.api.riotgames.com/riot/account/v1/region/by-game/lol/by-puuid/{puuid}"
        async with session.get(region_url, headers={"X-Riot-Token": RIOT_API_KEY}) as response:
            if response.status == 200:
                data = await response.json()
                region = data.get("region")
                if region:
                    print(f"Active region detected for {puuid}: {region}")
                    return region.upper()
                return None
            else:
                print(f"Failed to fetch active region for {puuid}: status {response.status}")
                return None
    except Exception as e:
        print(f"Error fetching active region for {puuid}: {e}")
        return None

# Routing resolver function
def get_routing_cluster(tag_line: str = None, active_region: str = None) -> str:
    """Return 'americas' | 'europe' | 'asia' | 'sea' from a Riot region/tagLine like NA1, EUW1, KR, OC1, SG2, PH2, ME1, etc."""
    # If we have an active_region from the API, use it first
    if active_region:
        t = active_region.upper()
    else:
        t = (tag_line or "").upper()

    americas = {"NA", "NA1", "BR", "BR1", "LA1", "LA2", "LAN", "LAS"}
    europe   = {"EUW", "EUW1", "EUN1", "EUNE", "TR1", "TR", "RU", "ME1"}
    asia     = {"KR", "JP1", "JP"}
    sea      = {"OC1", "OCE", "SG2", "PH2", "TW2", "VN2", "TH2"}

    if t in americas: return "americas"
    if t in europe:   return "europe"
    if t in asia:     return "asia"
    if t in sea:      return "sea"
    # Safe fallback
    return "americas"

# Updated `/get-stats` endpoint to use dynamic routing
@app.route("/get-stats", methods=["GET"])
async def get_stats():
    """Fetches stats for the last year, updates the database incrementally, and generates insights."""
    game_name = request.args.get("gameName")
    tag_line = request.args.get("tagLine")

    if not game_name or not tag_line:
        return jsonify({"error": "Missing required parameters: gameName and tagLine."}), 400

    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Get PUUID using Riot Account-V1 API
            account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
            async with session.get(account_url, headers={"X-Riot-Token": RIOT_API_KEY}) as account_response:
                if account_response.status == 403:
                    return jsonify({"error": "Invalid or expired API key."}), 403
                elif account_response.status == 404:
                    return jsonify({"error": "Account not found."}), 404
                elif account_response.status != 200:
                    return jsonify({"error": "Failed to fetch account data."}), account_response.status

                account_data = await account_response.json()
                puuid = account_data.get("puuid")

                if not puuid:
                    return jsonify({"error": "PUUID not found in account data."}), 500

            # Get active region from Riot API
            active_region = await get_active_region(session, puuid)
            routing = get_routing_cluster(tag_line=tag_line, active_region=active_region)

            # Step 2: Determine the start time for fetching matches
            last_match = Match.query.filter_by(puuid=puuid).order_by(Match.timestamp.desc()).first()
            start_time = (
                int(last_match.timestamp / 1000)
                if last_match
                else int((datetime.now() - timedelta(days=365)).timestamp())
            )

            # Step 3: Fetch match IDs incrementally
            matches_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
            match_ids = []
            start = 0

            async def fetch_match_ids(start):
                paginated_url = f"{matches_url}?startTime={start_time}&start={start}&count=100"
                retries = 0
                while retries < 5:
                    async with session.get(paginated_url, headers={"X-Riot-Token": RIOT_API_KEY}) as matches_response:
                        if matches_response.status == 429:
                            retry_after = int(matches_response.headers.get("Retry-After", 120))
                            print(f"Rate limit hit. Retrying after {retry_after} seconds.")
                            await asyncio.sleep(retry_after)
                            retries += 1
                            continue
                        elif matches_response.status in {400, 401, 403, 404, 405, 415, 500, 502, 503, 504}:
                            print(f"Error fetching match IDs. HTTP Status: {matches_response.status}")
                            return []
                        elif matches_response.status != 200:
                            print(f"Unexpected error. HTTP Status: {matches_response.status}")
                            return []
                        return await matches_response.json()
                    retries += 1
                    await asyncio.sleep(2 ** retries)  # Exponential backoff
                print("Max retries reached for fetching match IDs.")
                return []

            request_count = 0
            start_time_window = datetime.now()

            while True:
                # Check rate limits
                if request_count >= 20:
                    elapsed_time = (datetime.now() - start_time_window).total_seconds()
                    if elapsed_time < 1:
                        await asyncio.sleep(1 - elapsed_time)
                    request_count = 0
                    start_time_window = datetime.now()

                batch_ids = await fetch_match_ids(start)
                request_count += 1

                if not batch_ids:
                    print("No more matches returned by the API.")
                    break
                match_ids.extend(batch_ids)
                print(f"Fetched {len(batch_ids)} matches in this batch. Total so far: {len(match_ids)}")
                await asyncio.sleep(1.2)  # small delay between ID pages
                start += 100

            # Debugging: Log the total number of match IDs fetched
            print(f"Total match IDs fetched: {len(match_ids)}")

            # Step 4: Fetch match details for new matches only
            existing_pairs = set(
                (m.id, m.puuid)
                for m in db.session.query(Match.id, Match.puuid)
                .filter(Match.id.in_(match_ids))
                .all()
            )
            # Debug: distinguish between matches for THIS PLAYER vs OTHER PLAYERS
            existing_for_this_user = [
                (mid, p) for (mid, p) in existing_pairs if p == puuid
            ]

            existing_for_other_players = [
                (mid, p) for (mid, p) in existing_pairs if p != puuid
            ]

            print(f"Existing match_id+puuid pairs for THIS player: {len(existing_for_this_user)}")
            print(f"Existing match_id+puuid pairs for OTHER players: {len(existing_for_other_players)}")
            print(f"Total overlapping match IDs: {len(existing_pairs)}")
            new_ids = [
                mid for mid in match_ids
                if (mid, puuid) not in existing_pairs
            ]
            print(f"New match IDs to fetch details for: {len(new_ids)}")

            # Define the detail fetcher
            async def fetch_match_details(match_id, session, puuid):
                match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
                retries = 0
                while retries < 5:
                    async with session.get(match_url, headers={"X-Riot-Token": RIOT_API_KEY}) as match_response:
                        if match_response.status == 429:
                            retry_after = int(match_response.headers.get("Retry-After", 120))
                            print(f"Rate limit hit for {match_id}, retrying in {retry_after}s")
                            await asyncio.sleep(retry_after)
                            retries += 1
                            continue
                        if match_response.status != 200:
                            print(f"Failed match {match_id}, status {match_response.status}")
                            return None
                        match_data = await match_response.json()
                        info = match_data.get("info", {})
                        participants = info.get("participants", [])
                        teams = info.get("teams", [])

                        # Locate the participant with the matching PUUID
                        participant = next((p for p in participants if p["puuid"] == puuid), None)
                        if not participant:
                            print(f"No participant for {puuid} in match {match_id}")
                            return None

                        # Compute team totals
                        team_id = participant["teamId"]
                        team_participants = [p for p in participants if p["teamId"] == team_id]
                        team_kills = sum(p["kills"] for p in team_participants)
                        team_damage = sum(p["totalDamageDealtToChampions"] for p in team_participants)
                        team_gold = sum(p["goldEarned"] for p in team_participants)
                        team_vision = sum(p["visionScore"] for p in team_participants)

                        # Extract objective stats
                        team_objectives = next((t for t in teams if t["teamId"] == team_id), {}).get("objectives", {})
                        dragons = team_objectives.get("dragon", {}).get("kills", 0)
                        barons = team_objectives.get("baron", {}).get("kills", 0)
                        heralds = team_objectives.get("riftHerald", {}).get("kills", 0)
                        towers = team_objectives.get("tower", {}).get("kills", 0)
                        inhibitors = team_objectives.get("inhibitor", {}).get("kills", 0)

                        # Return a Match instance with all fields populated
                        return Match(
                            id=match_id,
                            game_mode=info.get("gameMode", "UNKNOWN"),
                            duration=info.get("gameDuration", 0),
                            win=participant.get("win", False),
                            timestamp=info.get("gameStartTimestamp", 0),

                            # Identity
                            role=participant.get("teamPosition", "UNKNOWN"),
                            champion=participant.get("championName", "Unknown"),
                            puuid=puuid,

                            # Core Combat Stats
                            kills=participant.get("kills", 0),
                            deaths=participant.get("deaths", 0),
                            assists=participant.get("assists", 0),
                            damage=participant.get("totalDamageDealtToChampions", 0),
                            damage_taken=participant.get("totalDamageTaken", 0),
                            time_dead=participant.get("totalTimeSpentDead", 0),

                            # Economy
                            gold=participant.get("goldEarned", 0),

                            # Farming
                            cs=participant.get("totalMinionsKilled", 0),
                            neutral_cs=participant.get("neutralMinionsKilled", 0),
                            enemy_jungle_cs=participant.get("totalEnemyJungleMinionsKilled", 0),
                            ally_jungle_cs=participant.get("totalAllyJungleMinionsKilled", 0),

                            # Vision
                            vision=participant.get("visionScore", 0),
                            wards_placed=participant.get("wardsPlaced", 0),
                            wards_killed=participant.get("wardsKilled", 0),

                            # Objectives
                            dragons=dragons,
                            barons=barons,
                            heralds=heralds,
                            towers=towers,
                            inhibitors=inhibitors,

                            # Team Totals
                            team_kills=team_kills,
                            team_damage=team_damage,
                            team_gold=team_gold,
                            team_vision=team_vision
                        )
                    retries += 1
                    await asyncio.sleep(2 ** retries)
                print(f"Max retries reached for match {match_id}")
                return None

            # --- Limit concurrency to avoid 429 ---
            semaphore = asyncio.Semaphore(15)

            async def safe_fetch(mid):
                async with semaphore:
                    data = await fetch_match_details(mid, session, puuid)
                    await asyncio.sleep(1.3)
                    return data

            results = []
            for i in range(0, len(new_ids), 15):
                batch = new_ids[i:i+15]
                batch_results = await asyncio.gather(*(safe_fetch(mid) for mid in batch))
                results.extend(batch_results)
                print(f"Processed batch {i//15 + 1}/{(len(new_ids)+14)//15}")

            new_matches = [m for m in results if m]
            print(f"Total new matches processed: {len(new_matches)}")

            # Step 5: Insert new matches into the database in smaller batches using execute_values
            if new_matches:
                batch_size = 50  # Define the batch size
                try:
                    for i in range(0, len(new_matches), batch_size):
                        batch = new_matches[i:i + batch_size]

                        # Corrected values to match the Match model schema
                        values = [
                            (
                                match.id,
                                match.game_mode,
                                match.duration,
                                match.win,
                                match.timestamp,

                                # Identity
                                match.role,
                                match.champion,
                                match.puuid,

                                # Core Combat Stats
                                match.kills,
                                match.deaths,
                                match.assists,
                                match.damage,
                                match.damage_taken,
                                match.time_dead,

                                # Economy
                                match.gold,

                                # Farming
                                match.cs,
                                match.neutral_cs,
                                match.enemy_jungle_cs,
                                match.ally_jungle_cs,

                                # Vision
                                match.vision,
                                match.wards_placed,
                                match.wards_killed,

                                # Objectives
                                match.dragons,
                                match.barons,
                                match.heralds,
                                match.towers,
                                match.inhibitors,

                                # Team Totals
                                match.team_kills,
                                match.team_damage,
                                match.team_gold,
                                match.team_vision
                            )
                            for match in batch
                        ]

                        retries = 3
                        while retries > 0:
                            try:
                                conn = db.engine.raw_connection()
                                try:
                                    with conn.cursor() as cursor:
                                        execute_values(
                                            cursor,
                                            """
                                            INSERT INTO match (
                                                id, game_mode, duration, win, timestamp,
                                                role, champion, puuid,
                                                kills, deaths, assists, damage, damage_taken, time_dead,
                                                gold,
                                                cs, neutral_cs, enemy_jungle_cs, ally_jungle_cs,
                                                vision, wards_placed, wards_killed,
                                                dragons, barons, heralds, towers, inhibitors,
                                                team_kills, team_damage, team_gold, team_vision
                                            )
                                            VALUES %s
                                            """,
                                            values
                                        )
                                    conn.commit()
                                finally:
                                    conn.close()

                                print(f"Inserted batch {i // batch_size + 1}/{(len(new_matches) + batch_size - 1) // batch_size}")
                                break  # Exit retry loop on success
                            except psycopg2.OperationalError as e:
                                retries -= 1
                                print(f"Database operation failed. Retries left: {retries}. Error: {e}")
                                if retries == 0:
                                    raise
                                await asyncio.sleep(2)  # Wait before retrying

                    print(f"Successfully inserted {len(new_matches)} matches into the database.")
                    reset_db_connection()

                except Exception as e:
                    print(f"Error inserting matches into the database: {e}")

            # Step 6: Combine all matches (existing + new) and generate insights
            reset_db_connection()
            all_matches = Match.query.filter_by(puuid=puuid).all()
            print(f"Total matches in database after insertion: {len(all_matches)}")

            total_matches = len(all_matches)
            if total_matches == 0:
                return jsonify({
                    "gameName": game_name,
                    "tagLine": tag_line,
                    "puuid": puuid,
                    "total_matches": 0,
                    "message": "No matches found for this player."
                })

            total_wins = sum(1 for match in all_matches if match.win)
            total_kills = sum(m.kills for m in all_matches)
            total_deaths = sum(m.deaths for m in all_matches)
            total_assists = sum(m.assists for m in all_matches)

            champion_count = defaultdict(int)
            game_mode_count = defaultdict(int)

            for match in all_matches:
                champion_count[match.champion] += 1
                game_mode_count[match.game_mode] += 1

            avg_kills = total_kills / total_matches
            avg_deaths = total_deaths / total_matches
            avg_assists = total_assists / total_matches
            win_rate = (total_wins / total_matches) * 100

            most_played_champion = max(champion_count, key=champion_count.get, default="Unknown")

            # --- Enhanced Analytics ---
            role_stats = defaultdict(lambda: defaultdict(float))
            role_count = defaultdict(int)

            total_kp = 0
            total_damage_share = 0
            total_gold_share = 0
            total_vision_share = 0
            total_cs_per_min = 0

            for match in all_matches:
                # Kill Participation
                kp = (match.kills + match.assists) / match.team_kills if match.team_kills > 0 else 0
                total_kp += kp

                # Damage Share
                damage_share = match.damage / match.team_damage if match.team_damage > 0 else 0
                total_damage_share += damage_share

                # Gold Share
                gold_share = match.gold / match.team_gold if match.team_gold > 0 else 0
                total_gold_share += gold_share

                # Vision Share
                vision_share = match.vision / match.team_vision if match.team_vision > 0 else 0
                total_vision_share += vision_share

                # CS Per Minute
                cs_per_min = (match.cs + match.neutral_cs) / (match.duration / 60) if match.duration > 0 else 0
                total_cs_per_min += cs_per_min

                # Role Breakdown
                role = match.role
                role_count[role] += 1
                role_stats[role]['kills'] += match.kills
                role_stats[role]['deaths'] += match.deaths
                role_stats[role]['assists'] += match.assists
                role_stats[role]['damage'] += match.damage
                role_stats[role]['cs'] += match.cs + match.neutral_cs
                role_stats[role]['kp'] += kp

            # Compute averages for roles
            for role, stats in role_stats.items():
                count = role_count[role]
                if count > 0:
                    role_stats[role]['avg_kills'] = round(stats['kills'] / count, 2)
                    role_stats[role]['avg_deaths'] = round(stats['deaths'] / count, 2)
                    role_stats[role]['avg_assists'] = round(stats['assists'] / count, 2)
                    role_stats[role]['avg_damage'] = round(stats['damage'] / count, 2)
                    role_stats[role]['avg_cs'] = round(stats['cs'] / count, 2)
                    role_stats[role]['avg_kp'] = round((stats['kp'] / count) * 100, 2)

            # --- Role Impact Stats ---
            role_impact_stats = defaultdict(lambda: defaultdict(float))
            role_impact_counts = defaultdict(int)

            for match in all_matches:
                role = match.role

                # Skip matches where the denominator is 0
                if match.team_damage > 0:
                    damage_share = match.damage / match.team_damage
                    role_impact_stats[role]['damage_share'] += damage_share
                if match.team_gold > 0:
                    gold_share = match.gold / match.team_gold
                    role_impact_stats[role]['gold_share'] += gold_share
                if match.team_vision > 0:
                    vision_share = match.vision / match.team_vision
                    role_impact_stats[role]['vision_share'] += vision_share
                if match.team_kills > 0:
                    kp = (match.kills + match.assists) / match.team_kills
                    role_impact_stats[role]['kp'] += kp

                role_impact_counts[role] += 1

            # Compute averages for role impact stats
            for role, stats in role_impact_stats.items():
                count = role_impact_counts[role]
                if count > 0:
                    role_impact_stats[role]['avg_damage_share'] = round((stats['damage_share'] / count) * 100, 2)
                    role_impact_stats[role]['avg_gold_share'] = round((stats['gold_share'] / count) * 100, 2)
                    role_impact_stats[role]['avg_vision_share'] = round((stats['vision_share'] / count) * 100, 2)
                    role_impact_stats[role]['avg_kp'] = round((stats['kp'] / count) * 100, 2)

            # Ensure all required variables are defined
            avg_kills = total_kills / total_matches if total_matches > 0 else 0
            avg_deaths = total_deaths / total_matches if total_matches > 0 else 0
            avg_assists = total_assists / total_matches if total_matches > 0 else 0
            avg_cs_min = round(total_cs_per_min / total_matches, 2) if total_matches > 0 else 0
            avg_kp = round((total_kp / total_matches) * 100, 2) if total_matches > 0 else 0
            avg_damage_share = round((total_damage_share / total_matches) * 100, 2) if total_matches > 0 else 0
            avg_gold_share = round((total_gold_share / total_matches) * 100, 2) if total_matches > 0 else 0
            avg_vision_share = round((total_vision_share / total_matches) * 100, 2) if total_matches > 0 else 0

            # --- Extreme Game Analytics ---
            def kda(match):
                return (match.kills + match.assists) / match.deaths if match.deaths > 0 else match.kills + match.assists

            highest_kill_game = max(all_matches, key=lambda m: m.kills)
            highest_death_game = max(all_matches, key=lambda m: m.deaths)
            highest_assist_game = max(all_matches, key=lambda m: m.assists)
            highest_damage_game = max(all_matches, key=lambda m: m.damage)
            highest_damage_taken_game = max(all_matches, key=lambda m: m.damage_taken)
            highest_cs_game = max(all_matches, key=lambda m: m.cs + m.neutral_cs)
            highest_cs_per_min_game = max(all_matches, key=lambda m: (m.cs + m.neutral_cs) / (m.duration / 60) if m.duration > 0 else 0)
            best_kda_game = max(all_matches, key=kda)
            worst_kda_game = min(all_matches, key=kda)
            fastest_game = min(all_matches, key=lambda m: m.duration)
            longest_game = max(all_matches, key=lambda m: m.duration)

            extreme_games = {
                "highest_kill_game": {
                    "match_id": highest_kill_game.id,
                    "kills": highest_kill_game.kills,
                    "champion": highest_kill_game.champion,
                    "role": highest_kill_game.role
                },
                "highest_death_game": {
                    "match_id": highest_death_game.id,
                    "deaths": highest_death_game.deaths,
                    "champion": highest_death_game.champion,
                    "role": highest_death_game.role
                },
                "highest_assist_game": {
                    "match_id": highest_assist_game.id,
                    "assists": highest_assist_game.assists,
                    "champion": highest_assist_game.champion,
                    "role": highest_assist_game.role
                },
                "highest_damage_game": {
                    "match_id": highest_damage_game.id,
                    "damage": highest_damage_game.damage,
                    "champion": highest_damage_game.champion,
                    "role": highest_damage_game.role
                },
                "highest_damage_taken_game": {
                    "match_id": highest_damage_taken_game.id,
                    "damage_taken": highest_damage_taken_game.damage_taken,
                    "champion": highest_damage_taken_game.champion,
                    "role": highest_damage_taken_game.role
                },
                "highest_cs_game": {
                    "match_id": highest_cs_game.id,
                    "cs": highest_cs_game.cs + highest_cs_game.neutral_cs,
                    "champion": highest_cs_game.champion,
                    "role": highest_cs_game.role
                },
                "highest_cs_per_min_game": {
                    "match_id": highest_cs_per_min_game.id,
                    "cs_per_min": round((highest_cs_per_min_game.cs + highest_cs_per_min_game.neutral_cs) / (highest_cs_per_min_game.duration / 60), 2) if highest_cs_per_min_game.duration > 0 else 0,
                    "champion": highest_cs_per_min_game.champion,
                    "role": highest_cs_per_min_game.role
                },
                "best_kda_game": {
                    "match_id": best_kda_game.id,
                    "kda": round(kda(best_kda_game), 2),
                    "kills": best_kda_game.kills,
                    "deaths": best_kda_game.deaths,
                    "assists": best_kda_game.assists,
                    "champion": best_kda_game.champion,
                    "role": best_kda_game.role
                },
                "worst_kda_game": {
                    "match_id": worst_kda_game.id,
                    "kda": round(kda(worst_kda_game), 2),
                    "kills": worst_kda_game.kills,
                    "deaths": worst_kda_game.deaths,
                    "assists": worst_kda_game.assists,
                    "champion": worst_kda_game.champion,
                    "role": worst_kda_game.role
                },
                "fastest_game": {
                    "match_id": fastest_game.id,
                    "duration": fastest_game.duration,
                    "champion": fastest_game.champion,
                    "role": fastest_game.role
                },
                "longest_game": {
                    "match_id": longest_game.id,
                    "duration": longest_game.duration,
                    "champion": longest_game.champion,
                    "role": longest_game.role
                }
            }

            # --- Monthly Visualization Data ---
            monthly_stats = {}
            monthly_roles = {}
            monthly_champions = {}

            for match in all_matches:
                month = datetime.fromtimestamp(match.timestamp / 1000).strftime("%Y-%m")
                
                # Initialize month if not exists
                if month not in monthly_stats:
                    monthly_stats[month] = {
                        "matches": 0,
                        "wins": 0,
                        "total_kills": 0,
                        "total_deaths": 0,
                        "total_assists": 0,
                        "total_cs": 0,
                        "total_duration": 0,
                        "total_kp": 0,
                        "total_damage_share": 0,
                        "total_gold_share": 0
                    }
                    monthly_roles[month] = defaultdict(int)
                    monthly_champions[month] = defaultdict(int)
                
                # Update monthly stats
                monthly_stats[month]["matches"] += 1
                if match.win:
                    monthly_stats[month]["wins"] += 1
                monthly_stats[month]["total_kills"] += match.kills
                monthly_stats[month]["total_deaths"] += match.deaths
                monthly_stats[month]["total_assists"] += match.assists
                monthly_stats[month]["total_cs"] += match.cs + match.neutral_cs
                monthly_stats[month]["total_duration"] += match.duration
                
                # KP
                if match.team_kills > 0:
                    monthly_stats[month]["total_kp"] += (match.kills + match.assists) / match.team_kills
                
                # Damage share
                if match.team_damage > 0:
                    monthly_stats[month]["total_damage_share"] += match.damage / match.team_damage
                
                # Gold share
                if match.team_gold > 0:
                    monthly_stats[month]["total_gold_share"] += match.gold / match.team_gold
                
                # Monthly roles
                monthly_roles[month][match.role] += 1
                
                # Monthly champions
                monthly_champions[month][match.champion] += 1

            # Compute monthly averages
            for month, stats in monthly_stats.items():
                matches_count = stats["matches"]
                if matches_count > 0:
                    stats["winrate"] = round((stats["wins"] / matches_count) * 100, 2)
                    stats["avg_kills"] = round(stats["total_kills"] / matches_count, 2)
                    stats["avg_deaths"] = round(stats["total_deaths"] / matches_count, 2)
                    stats["avg_assists"] = round(stats["total_assists"] / matches_count, 2)
                    stats["avg_cs_per_min"] = round((stats["total_cs"] / matches_count) / ((stats["total_duration"] / matches_count) / 60), 2) if stats["total_duration"] > 0 else 0
                    stats["avg_kp"] = round((stats["total_kp"] / matches_count) * 100, 2)
                    stats["avg_damage_share"] = round((stats["total_damage_share"] / matches_count) * 100, 2)
                    stats["avg_gold_share"] = round((stats["total_gold_share"] / matches_count) * 100, 2)
                    
                    # Clean up intermediate totals
                    del stats["total_kills"]
                    del stats["total_deaths"]
                    del stats["total_assists"]
                    del stats["total_cs"]
                    del stats["total_duration"]
                    del stats["total_kp"]
                    del stats["total_damage_share"]
                    del stats["total_gold_share"]

            # Convert defaultdicts to regular dicts
            monthly_roles = {month: dict(roles) for month, roles in monthly_roles.items()}
            monthly_champions = {month: dict(champions) for month, champions in monthly_champions.items()}

            # Final JSON response
            return jsonify({
                "profile": {
                    "gameName": game_name,
                    "tagLine": tag_line,
                    "puuid": puuid,
                    "total_matches": total_matches,
                    "total_wins": total_wins,
                    "total_losses": total_matches - total_wins,
                    "win_rate": f"{win_rate:.2f}"
                },
                "core_averages": {
                    "kills": round(avg_kills, 2),
                    "deaths": round(avg_deaths, 2),
                    "assists": round(avg_assists, 2),
                    "cs_per_min": avg_cs_min
                },
                "impact_stats": {
                    "kill_participation": avg_kp,
                    "damage_share": avg_damage_share,
                    "gold_share": avg_gold_share,
                    "vision_share": avg_vision_share
                },
                "role_distribution": dict(role_count),
                "role_performance": {role: dict(stats) for role, stats in role_stats.items()},
                "role_impact_stats": {role: dict(stats) for role, stats in role_impact_stats.items()},
                "most_played_champion": most_played_champion,
                "game_mode_distribution": dict(game_mode_count),
                "extreme_games": extreme_games,
                "monthly_stats": monthly_stats,
                "monthly_roles": monthly_roles,
                "monthly_champions": monthly_champions
            })

    except aiohttp.ClientError as e:
        return jsonify({"error": "An error occurred while communicating with the Riot Games API.", "details": str(e)}), 500

    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500

# ================================================================================================
# NEW TIMELINE SYSTEM - Single Model, Two Endpoints
# ================================================================================================

# `/process-timelines` - Fetch and process timeline insights for all existing matches
@app.route("/process-timelines", methods=["GET"])
async def process_timelines():
    """Process timeline insights for all existing matches in the database."""
    game_name = request.args.get("gameName")
    tag_line = request.args.get("tagLine")

    print(f"[TIMELINE] ==================== STARTING TIMELINE PROCESSING ====================")
    print(f"[TIMELINE] Fetching account data for gameName={game_name} tagLine={tag_line}")

    if not game_name or not tag_line:
        print("[TIMELINE] ERROR: Missing required parameters")
        return jsonify({"error": "Missing required parameters: gameName and tagLine."}), 400

    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Get PUUID using Riot Account-V1 API
            account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
            print(f"[TIMELINE] Account API URL: {account_url}")
            
            try:
                async with session.get(account_url, headers={"X-Riot-Token": RIOT_API_KEY}) as account_response:
                    print(f"[TIMELINE] Account response status: {account_response.status}")
                    if account_response.status != 200:
                        print(f"[TIMELINE] ERROR: Failed to fetch account, status={account_response.status}")
                        return jsonify({"error": "Failed to fetch account"}), account_response.status
                    account_data = await account_response.json()
                    puuid = account_data.get("puuid")
                    if not puuid:
                        print("[TIMELINE] ERROR: PUUID not found in response")
                        return jsonify({"error": "PUUID not found"}), 500
                    print(f"[TIMELINE] PUUID resolved: {puuid}")
            except Exception as e:
                print(f"[TIMELINE] ERROR: Exception during account fetch: {e}")
                raise

            # Get active region and routing
            print(f"[TIMELINE] Fetching active region for PUUID={puuid}")
            active_region = await get_active_region(session, puuid)
            print(f"[TIMELINE] Active region: {active_region}")
            
            routing = get_routing_cluster(tag_line=tag_line, active_region=active_region)
            print(f"[TIMELINE] Routing cluster: {routing}")

            # Step 2: Get ALL match_ids from database for this PUUID
            print(f"[TIMELINE] Querying database for matches with puuid={puuid}")
            matches = Match.query.filter_by(puuid=puuid).all()
            match_ids = [m.id for m in matches]
            print(f"[TIMELINE] Total matches in DB: {len(match_ids)}")
            
            if not match_ids:
                print("[TIMELINE] ERROR: No matches found in database")
                return jsonify({"error": "No matches found in database. Run /get-stats first."}), 404

            # Step 3: Check which matches already have timeline summaries
            print(f"[TIMELINE] Checking existing timeline summaries for puuid={puuid}")
            existing_summaries = set(
                (s.match_id, s.puuid) 
                for s in MatchTimelineSummary.query.filter_by(puuid=puuid).all()
            )
            print(f"[TIMELINE] Existing summaries count: {len(existing_summaries)}")
            
            new_match_ids = [mid for mid in match_ids if (mid, puuid) not in existing_summaries]
            print(f"[TIMELINE] Matches without timeline summaries: {len(new_match_ids)}")
            print(f"[TIMELINE] Total matches: {len(match_ids)}, Already processed: {len(existing_summaries)}, To process: {len(new_match_ids)}")

            # Step 4: Process each new match
            processed = 0
            skipped = len(existing_summaries)

            async def process_single_match(match_id, match_duration, index, total):
                """Process timeline for a single match and extract insights."""
                print(f"[TIMELINE] Processing match {match_id} ({index}/{total})")
                timeline_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
                print(f"[TIMELINE] Fetching timeline URL: {timeline_url}")
                retries = 0
                
                while retries < 5:
                    try:
                        async with session.get(timeline_url, headers={"X-Riot-Token": RIOT_API_KEY}) as response:
                            print(f"[TIMELINE] Timeline status {response.status} for match {match_id}")
                            if response.status == 429:
                                retry_after = int(response.headers.get("Retry-After", 120))
                                print(f"[TIMELINE] Rate limit hit for {match_id}, retrying in {retry_after}s")
                                await asyncio.sleep(retry_after)
                                retries += 1
                                continue
                            elif response.status != 200:
                                print(f"[TIMELINE] ERROR: Failed to fetch timeline for {match_id}: {response.status}")
                                return None
                            
                            timeline = await response.json()
                            print(f"[TIMELINE] Timeline data received for {match_id}")
                            
                            # Extract participant mappings
                            print(f"[TIMELINE] Extracting participant->puuid map for {match_id}")
                            info = timeline.get("info", {})
                            if not info:
                                print(f"[TIMELINE] ERROR: No 'info' key in timeline for {match_id}")
                                return None
                            
                            participants_meta = info.get("participants", [])
                            if not participants_meta:
                                print(f"[TIMELINE] ERROR: No participants metadata for {match_id}")
                                return None
                            
                            pid_to_puuid = {p["participantId"]: p["puuid"] for p in participants_meta}
                            print(f"[TIMELINE] Built participantId->PUUID map with {len(pid_to_puuid)} entries")
                            
                            my_pid = next((pid for pid, p in pid_to_puuid.items() if p == puuid), None)
                            if not my_pid:
                                print(f"[TIMELINE] ERROR: Player PUUID {puuid} not found in match {match_id}")
                                return None
                            print(f"[TIMELINE] my_pid resolved = {my_pid}")

                            # Fetch match data to get team info
                            match_data = None
                            participants = []
                            my_team_id = None
                            
                            match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
                            print(f"[TIMELINE] Fetching match data URL: {match_url}")
                            try:
                                async with session.get(match_url, headers={"X-Riot-Token": RIOT_API_KEY}) as m_response:
                                    print(f"[TIMELINE] Match data status: {m_response.status}")
                                    if m_response.status == 200:
                                        match_data = await m_response.json()
                                        participants = match_data.get("info", {}).get("participants", [])
                                        print(f"[TIMELINE] Got {len(participants)} participants from match data")
                                        my_team_id = next((p.get("teamId") for p in participants if p.get("puuid") == puuid), None)
                                        print(f"[TIMELINE] my_team_id resolved = {my_team_id}")
                                    else:
                                        print(f"[TIMELINE] WARNING: Failed to fetch match data, status={m_response.status}")
                            except Exception as e:
                                print(f"[TIMELINE] ERROR: Exception fetching match data: {e}")

                            # Process frames
                            frames = info.get("frames", [])
                            print(f"[TIMELINE] Frames count: {len(frames)}")
                            
                            gold_diffs = []
                            level_6_time = None
                            level_11_time = None
                            level_16_time = None
                            positions = []
                            
                            for frame_idx, frame in enumerate(frames):
                                ts = frame.get("timestamp", 0)
                                if frame_idx % 50 == 0:
                                    print(f"[TIMELINE] Frame {frame_idx}: ts={ts}")
                                
                                pf_all = frame.get("participantFrames", {})
                                if not pf_all:
                                    if frame_idx % 50 == 0:
                                        print(f"[TIMELINE] WARNING: No participantFrames at frame {frame_idx}")
                                    continue
                                
                                if frame_idx % 50 == 0:
                                    print(f"[TIMELINE] pf keys: {list(pf_all.keys())}")
                                
                                pf = pf_all.get(str(my_pid))
                                if not pf:
                                    if frame_idx % 50 == 0:
                                        print(f"[TIMELINE] WARNING: No data for my_pid={my_pid} at frame {frame_idx}")
                                    continue
                                
                                # Track level milestones
                                level = pf.get("level", 1)
                                if level >= 6 and level_6_time is None:
                                    level_6_time = ts
                                    print(f"[TIMELINE] MILESTONE: Level 6 reached at {ts}ms")
                                if level >= 11 and level_11_time is None:
                                    level_11_time = ts
                                    print(f"[TIMELINE] MILESTONE: Level 11 reached at {ts}ms")
                                if level >= 16 and level_16_time is None:
                                    level_16_time = ts
                                    print(f"[TIMELINE] MILESTONE: Level 16 reached at {ts}ms")
                                
                                # Calculate gold diff
                                my_gold = int(pf.get("totalGold", 0))
                                enemy_golds = []
                                
                                for pid_str, other_pf in pf_all.items():
                                    pid_int = int(pid_str)
                                    if pid_int == my_pid:
                                        continue
                                    
                                    other_puuid = pid_to_puuid.get(pid_int)
                                    if other_puuid and match_data and my_team_id:
                                        for p in participants:
                                            if p.get("puuid") == other_puuid and p.get("teamId") != my_team_id:
                                                enemy_golds.append(int(other_pf.get("totalGold", 0)))
                                                break
                                
                                if enemy_golds:
                                    avg_enemy_gold = sum(enemy_golds) // len(enemy_golds)
                                    gold_diff = my_gold - avg_enemy_gold
                                    gold_diffs.append((ts, gold_diff))
                                    if frame_idx % 50 == 0:
                                        print(f"[TIMELINE] Frame {frame_idx}: my_gold={my_gold} enemy_gold_avg={avg_enemy_gold} diff={gold_diff}")
                                
                                # Track position for roam score
                                pos = pf.get("position", {})
                                if pos.get("x") is not None and pos.get("y") is not None:
                                    positions.append((pos.get("x"), pos.get("y")))

                            print(f"[TIMELINE] Completed frame processing. Total gold_diffs: {len(gold_diffs)}, positions: {len(positions)}")

                            # Process events
                            print(f"[TIMELINE] Processing events for {match_id}")
                            kill_positions = []
                            objective_counts = {"dragon": 0, "baron": 0, "herald": 0, "tower": 0, "inhibitor": 0}
                            
                            for frame in frames:
                                for event in frame.get("events", []):
                                    event_type = event.get("type")
                                    
                                    if event_type == "CHAMPION_KILL":
                                        killer_pid = event.get("killerId")
                                        if killer_pid == my_pid:
                                            pos = event.get("position", {})
                                            if pos.get("x") is not None and pos.get("y") is not None:
                                                kill_positions.append({"x": pos.get("x"), "y": pos.get("y")})
                                                print(f"[EVENT] Kill at x={pos.get('x')} y={pos.get('y')}")
                                    
                                    elif event_type == "ELITE_MONSTER_KILL" and my_team_id:
                                        killer_pid = event.get("killerId")
                                        killer_puuid = pid_to_puuid.get(killer_pid)
                                        if killer_puuid:
                                            killer_team = next((p.get("teamId") for p in participants if p.get("puuid") == killer_puuid), None)
                                            if killer_team == my_team_id:
                                                monster_type = event.get("monsterType", "").lower()
                                                if "dragon" in monster_type:
                                                    objective_counts["dragon"] += 1
                                                    print(f"[EVENT] Dragon +1 (total: {objective_counts['dragon']})")
                                                elif "baron" in monster_type:
                                                    objective_counts["baron"] += 1
                                                    print(f"[EVENT] Baron +1 (total: {objective_counts['baron']})")
                                                elif "herald" in monster_type or "riftherald" in monster_type:
                                                    objective_counts["herald"] += 1
                                                    print(f"[EVENT] Herald +1 (total: {objective_counts['herald']})")
                                    
                                    elif event_type == "BUILDING_KILL" and my_team_id:
                                        killer_pid = event.get("killerId")
                                        killer_puuid = pid_to_puuid.get(killer_pid)
                                        if killer_puuid:
                                            killer_team = next((p.get("teamId") for p in participants if p.get("puuid") == killer_puuid), None)
                                            if killer_team == my_team_id:
                                                building_type = event.get("buildingType", "").lower()
                                                if "tower" in building_type:
                                                    objective_counts["tower"] += 1
                                                    print(f"[EVENT] Tower +1 (total: {objective_counts['tower']})")
                                                elif "inhibitor" in building_type:
                                                    objective_counts["inhibitor"] += 1
                                                    print(f"[EVENT] Inhibitor +1 (total: {objective_counts['inhibitor']})")

                            print(f"[TIMELINE] Event processing complete. Kills: {len(kill_positions)}, Objectives: {objective_counts}")

                            # Calculate insights
                            if not gold_diffs:
                                print(f"[TIMELINE] ERROR: No gold diffs calculated for {match_id}, cannot compute insights")
                                return None
                            
                            print(f"[TIMELINE] Computing insights for {match_id}")
                            
                            # Early dominance (0-10 min)
                            early_diffs = [diff for ts, diff in gold_diffs if ts <= 600000]
                            early_dominance = sum(early_diffs) / len(early_diffs) if early_diffs else 0
                            print(f"[INSIGHT] early_dominance={early_dominance:.2f} (computed from {len(early_diffs)} samples)")
                            
                            # Midgame swing (10-20 min)
                            mid_diffs = [diff for ts, diff in gold_diffs if 600000 < ts <= 1200000]
                            midgame_swing = max(mid_diffs) - min(mid_diffs) if len(mid_diffs) > 1 else 0
                            print(f"[INSIGHT] midgame_swing={midgame_swing:.2f} (computed from {len(mid_diffs)} samples)")
                            
                            # Consistency score (variance)
                            all_diffs = [diff for ts, diff in gold_diffs]
                            mean_diff = sum(all_diffs) / len(all_diffs) if all_diffs else 0
                            variance = sum((x - mean_diff) ** 2 for x in all_diffs) / len(all_diffs) if all_diffs else 0
                            consistency = 100 - min(variance / 100, 100)
                            print(f"[INSIGHT] consistency={consistency:.2f} (variance={variance:.2f}, mean={mean_diff:.2f})")
                            
                            # Biggest spike/throw
                            deltas = [all_diffs[i] - all_diffs[i-1] for i in range(1, len(all_diffs))]
                            biggest_spike = max(deltas) if deltas else 0
                            biggest_throw = min(deltas) if deltas else 0
                            print(f"[INSIGHT] spike={biggest_spike:.2f} throw={biggest_throw:.2f}")
                            
                            # Roam score (position changes)
                            roam_score = 0
                            if len(positions) > 1:
                                significant_moves = 0
                                for i in range(1, len(positions)):
                                    x1, y1 = positions[i-1]
                                    x2, y2 = positions[i]
                                    dist = ((x2-x1)**2 + (y2-y1)**2) ** 0.5
                                    if dist > 3000:  # Significant movement
                                        significant_moves += 1
                                roam_score = significant_moves / (len(positions) / 10)  # Normalize per 10 frames
                                print(f"[INSIGHT] roam_score={roam_score:.2f} (from {significant_moves} significant moves in {len(positions)} positions)")
                            else:
                                print(f"[INSIGHT] roam_score=0 (insufficient position data)")
                            
                            # Comeback type
                            comeback_type = "neutral"
                            if early_dominance > 100 and all_diffs[-1] > 500:
                                comeback_type = "dominated"
                            elif early_dominance < -100 and all_diffs[-1] > 500:
                                comeback_type = "comeback"
                            elif early_dominance > 100 and all_diffs[-1] < -500:
                                comeback_type = "throw"
                            elif early_dominance < -100 and all_diffs[-1] < -500:
                                comeback_type = "fell_behind"
                            print(f"[INSIGHT] comeback_type={comeback_type}")
                            
                            result = {
                                "match_id": match_id,
                                "puuid": puuid,
                                "early_dominance_score": round(early_dominance, 2),
                                "midgame_swing_score": round(midgame_swing, 2),
                                "consistency_score": round(consistency, 2),
                                "level_6_timestamp": level_6_time,
                                "level_11_timestamp": level_11_time,
                                "level_16_timestamp": level_16_time,
                                "biggest_spike": round(biggest_spike, 2),
                                "biggest_throw": round(biggest_throw, 2),
                                "roam_score": round(roam_score, 2),
                                "kill_positions": kill_positions,
                                "objective_presence": objective_counts,
                                "comeback_type": comeback_type,
                                "duration": match_duration
                            }
                            print(f"[TIMELINE] Successfully processed match {match_id}")
                            return result
                    
                    except Exception as e:
                        print(f"[TIMELINE] ERROR: Exception processing match {match_id}: {e}")
                        import traceback
                        traceback.print_exc()
                        return None
                    
                    retries += 1
                    await asyncio.sleep(2 ** retries)
                
                print(f"[TIMELINE] ERROR: Max retries reached for {match_id}")
                return None

            # Process matches with rate limiting
            print(f"[TIMELINE] Starting batch processing with semaphore(10)")
            semaphore = asyncio.Semaphore(10)
            match_dict = {m.id: m.duration for m in matches if m.id in new_match_ids}
            print(f"[TIMELINE] Built match_dict with {len(match_dict)} entries")
            
            match_counter = 0
            
            async def safe_process(mid):
                nonlocal match_counter
                match_counter += 1
                async with semaphore:
                    result = await process_single_match(mid, match_dict[mid], match_counter, len(new_match_ids))
                    await asyncio.sleep(1.5)
                    return result

            results = []
            heartbeat_counter = 0
            for i in range(0, len(new_match_ids), 10):
                batch = new_match_ids[i:i+10]
                print(f"[TIMELINE] ===== Batch {i//10 + 1}/{(len(new_match_ids)+9)//10} starting =====")
                batch_results = await asyncio.gather(*(safe_process(mid) for mid in batch))
                successful = [r for r in batch_results if r]
                results.extend(successful)
                heartbeat_counter += len(batch)
                if heartbeat_counter % 10 == 0 or (i + 10) >= len(new_match_ids):
                    print(f"[HEARTBEAT] Processed {heartbeat_counter}/{len(new_match_ids)} timeline summaries... (results so far: {len(results)})")
                print(f"[TIMELINE] Batch {i//10 + 1} complete. Successful: {len(successful)}/{len(batch)}")

            print(f"[TIMELINE] All batches complete. Total results: {len(results)}")

            # Step 5: Insert into database
            if results:
                print(f"[DB] Inserting {len(results)} timeline summaries into database")
                try:
                    for idx, summary in enumerate(results):
                        new_summary = MatchTimelineSummary(**summary)
                        db.session.add(new_summary)
                        if (idx + 1) % 50 == 0:
                            print(f"[DB] Added {idx + 1}/{len(results)} to session")
                    
                    print(f"[DB] Committing transaction...")
                    db.session.commit()
                    processed = len(results)
                    print(f"[DB] Insert success. Committed {processed} timeline summaries")
                except Exception as e:
                    print(f"[DB] ERROR: Failed to insert summaries: {e}")
                    import traceback
                    traceback.print_exc()
                    db.session.rollback()
                    print(f"[DB] Transaction rolled back")
                    return jsonify({"error": "Failed to insert timeline summaries", "details": str(e)}), 500
            else:
                print(f"[DB] No results to insert")

            print(f"[TIMELINE] Resetting database connection")
            reset_db_connection()

            print(f"[TIMELINE DONE] processed={processed}, skipped={skipped}, total={len(match_ids)}")
            print(f"[TIMELINE] ==================== TIMELINE PROCESSING COMPLETE ====================")

            return jsonify({
                "processed": processed,
                "skipped": skipped,
                "gameName": game_name,
                "tagLine": tag_line,
                "puuid": puuid,
                "message": "Timeline insights processed successfully."
            }), 200

    except Exception as e:
        print(f"[TIMELINE] FATAL ERROR in process_timelines: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# `/get-timeline-stats` - Year-long aggregated timeline insights
@app.route("/get-timeline-stats", methods=["GET"])
async def get_timeline_stats():
    """Get aggregated timeline insights for a player (year-long stats)."""
    game_name = request.args.get("gameName")
    tag_line = request.args.get("tagLine")

    if not game_name or not tag_line:
        return jsonify({"error": "Missing required parameters: gameName and tagLine."}), 400

    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Get PUUID
            account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
            async with session.get(account_url, headers={"X-Riot-Token": RIOT_API_KEY}) as account_response:
                if account_response.status != 200:
                    return jsonify({"error": "Failed to fetch account"}), account_response.status
                account_data = await account_response.json()
                puuid = account_data.get("puuid")
                if not puuid:
                    return jsonify({"error": "PUUID not found"}), 500

        # Step 2: Load all timeline summaries for this PUUID
        rows = MatchTimelineSummary.query.filter_by(puuid=puuid).all()
        
        if not rows:
            return jsonify({"error": "No timeline data found. Run /process-timelines first."}), 404

        total_matches = len(rows)

        # Step 3: Compute averages
        avg_early_dom = sum(r.early_dominance_score for r in rows if r.early_dominance_score) / total_matches
        avg_mid_swing = sum(r.midgame_swing_score for r in rows if r.midgame_swing_score) / total_matches
        avg_consistency = sum(r.consistency_score for r in rows if r.consistency_score) / total_matches
        avg_roam = sum(r.roam_score for r in rows if r.roam_score) / total_matches
        avg_spike = sum(r.biggest_spike for r in rows if r.biggest_spike) / total_matches
        avg_throw = sum(r.biggest_throw for r in rows if r.biggest_throw) / total_matches
        
        level_6_times = [r.level_6_timestamp for r in rows if r.level_6_timestamp]
        level_11_times = [r.level_11_timestamp for r in rows if r.level_11_timestamp]
        level_16_times = [r.level_16_timestamp for r in rows if r.level_16_timestamp]
        
        avg_level6 = sum(level_6_times) / len(level_6_times) if level_6_times else 0
        avg_level11 = sum(level_11_times) / len(level_11_times) if level_11_times else 0
        avg_level16 = sum(level_16_times) / len(level_16_times) if level_16_times else 0

        average_insights = {
            "early_dominance": round(avg_early_dom, 2),
            "midgame_swing": round(avg_mid_swing, 2),
            "consistency_score": round(avg_consistency, 2),
            "roam_score": round(avg_roam, 2),
            "biggest_spike": round(avg_spike, 2),
            "biggest_throw": round(avg_throw, 2),
            "avg_level6_time": round(avg_level6 / 1000, 2) if avg_level6 else 0,  # Convert to seconds
            "avg_level11_time": round(avg_level11 / 1000, 2) if avg_level11 else 0,
            "avg_level16_time": round(avg_level16 / 1000, 2) if avg_level16 else 0
        }

        # Step 4: Playstyle identity
        early_label = "neutral early"
        if avg_early_dom > 100:
            early_label = "strong early"
        elif avg_early_dom < -100:
            early_label = "weak early"
        
        consistency_label = "moderately consistent"
        if avg_consistency > 70:
            consistency_label = "stable"
        elif avg_consistency < 40:
            consistency_label = "coinflip"
        
        roam_label = "moderate roamer"
        if avg_roam > 3.5:
            roam_label = "heavy roamer"
        elif avg_roam < 1.5:
            roam_label = "lane anchored"
        
        risk_profile = "high impact" if avg_spike > abs(avg_throw) else "high risk"

        playstyle_identity = {
            "early_game": early_label,
            "consistency": consistency_label,
            "roaming": roam_label,
            "risk_profile": risk_profile
        }

        # Step 5: Comeback pattern counts
        comeback_counts = {
            "comeback_wins": sum(1 for r in rows if r.comeback_type == "comeback"),
            "throws": sum(1 for r in rows if r.comeback_type == "throw"),
            "dominant_wins": sum(1 for r in rows if r.comeback_type == "dominated"),
            "fell_behind_losses": sum(1 for r in rows if r.comeback_type == "fell_behind"),
            "neutral_games": sum(1 for r in rows if r.comeback_type == "neutral")
        }

        # Step 6: Heatmap data
        all_kill_positions = []
        total_objectives = {"dragon": 0, "baron": 0, "herald": 0, "tower": 0, "inhibitor": 0}
        
        for r in rows:
            if r.kill_positions:
                all_kill_positions.extend(r.kill_positions)
            if r.objective_presence:
                for obj, count in r.objective_presence.items():
                    if obj in total_objectives:
                        total_objectives[obj] += count

        heatmap = {
            "kill_positions": all_kill_positions,
            "objectives": total_objectives
        }

        # Step 7: Most extreme games
        max_spike_game = max(rows, key=lambda r: r.biggest_spike if r.biggest_spike else 0)
        min_throw_game = min(rows, key=lambda r: r.biggest_throw if r.biggest_throw else 0)

        most_extreme_games = {
            "best_spike_game": {
                "match_id": max_spike_game.match_id,
                "spike": max_spike_game.biggest_spike,
                "early_dominance": max_spike_game.early_dominance_score,
                "comeback_type": max_spike_game.comeback_type
            },
            "worst_throw_game": {
                "match_id": min_throw_game.match_id,
                "throw": min_throw_game.biggest_throw,
                "early_dominance": min_throw_game.early_dominance_score,
                "comeback_type": min_throw_game.comeback_type
            }
        }

        # Step 8: Final response
        return jsonify({
            "puuid": puuid,
            "total_matches": total_matches,
            "average_insights": average_insights,
            "playstyle_identity": playstyle_identity,
            "comeback_pattern": comeback_counts,
            "heatmap": heatmap,
            "most_extreme_games": most_extreme_games
        }), 200

    except Exception as e:
        print(f"Error in get_timeline_stats: {e}")
        return jsonify({"error": str(e)}), 500


# ================================================================================================
# AWS BEDROCK INTEGRATION - AI-POWERED YEAR RECAP
# ================================================================================================

@app.route("/generate-recap", methods=["POST"])
async def generate_recap():
    """
    Generate an AI-powered year recap using AWS Bedrock (Claude).
    Combines stats and timeline data, then sends to Claude for narrative generation.
    """
    print("[RECAP] ==================== STARTING AI RECAP GENERATION ====================")
    
    if not bedrock:
        print("[RECAP] ERROR: AWS Bedrock client not initialized")
        return jsonify({"error": "AWS Bedrock not configured"}), 500
    
    data = request.get_json()
    game_name = data.get("gameName")
    tag_line = data.get("tagLine")
    
    if not game_name or not tag_line:
        print("[RECAP] ERROR: Missing required parameters")
        return jsonify({"error": "Missing required parameters: gameName and tagLine."}), 400
    
    print(f"[RECAP] Generating recap for {game_name}#{tag_line}")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Get PUUID
            print("[RECAP] Fetching account data...")
            account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
            async with session.get(account_url, headers={"X-Riot-Token": RIOT_API_KEY}) as account_response:
                if account_response.status != 200:
                    print(f"[RECAP] ERROR: Failed to fetch account: {account_response.status}")
                    return jsonify({"error": "Failed to fetch account"}), account_response.status
                account_data = await account_response.json()
                puuid = account_data.get("puuid")
                if not puuid:
                    print("[RECAP] ERROR: PUUID not found")
                    return jsonify({"error": "PUUID not found"}), 500
                print(f"[RECAP] PUUID resolved: {puuid}")
        
        # Step 2: Fetch stats data from database
        print("[RECAP] Querying database for stats...")
        all_matches = Match.query.filter_by(puuid=puuid).all()
        
        if not all_matches:
            print("[RECAP] ERROR: No matches found")
            return jsonify({"error": "No matches found. Run /get-stats first."}), 404
        
        total_matches = len(all_matches)
        total_wins = sum(1 for match in all_matches if match.win)
        total_kills = sum(m.kills for m in all_matches)
        total_deaths = sum(m.deaths for m in all_matches)
        total_assists = sum(m.assists for m in all_matches)
        
        champion_count = defaultdict(int)
        role_count = defaultdict(int)
        
        for match in all_matches:
            champion_count[match.champion] += 1
            role_count[match.role] += 1
        
        avg_kills = round(total_kills / total_matches, 2) if total_matches > 0 else 0
        avg_deaths = round(total_deaths / total_matches, 2) if total_matches > 0 else 0
        avg_assists = round(total_assists / total_matches, 2) if total_matches > 0 else 0
        win_rate = f"{(total_wins / total_matches) * 100:.2f}" if total_matches > 0 else "0"
        most_played_champion = max(champion_count, key=champion_count.get, default="Unknown")
        
        stats_json = {
            "profile": {
                "gameName": game_name,
                "tagLine": tag_line,
                "total_matches": total_matches,
                "total_wins": total_wins,
                "win_rate": win_rate
            },
            "core_averages": {
                "kills": avg_kills,
                "deaths": avg_deaths,
                "assists": avg_assists
            },
            "most_played_champion": most_played_champion,
            "role_distribution": dict(role_count)
        }
        
        print(f"[RECAP] Stats compiled: {total_matches} matches, {win_rate}% WR")
        
        # Step 3: Fetch timeline stats from database
        print("[RECAP] Querying database for timeline stats...")
        timeline_rows = MatchTimelineSummary.query.filter_by(puuid=puuid).all()
        
        if not timeline_rows:
            print("[RECAP] WARNING: No timeline data found, proceeding with stats only")
            cleaned_timeline = {"note": "No timeline data available"}
        else:
            # Compute averages
            total_timeline_matches = len(timeline_rows)
            avg_early_dom = sum(r.early_dominance_score for r in timeline_rows if r.early_dominance_score) / total_timeline_matches
            avg_mid_swing = sum(r.midgame_swing_score for r in timeline_rows if r.midgame_swing_score) / total_timeline_matches
            avg_consistency = sum(r.consistency_score for r in timeline_rows if r.consistency_score) / total_timeline_matches
            avg_roam = sum(r.roam_score for r in timeline_rows if r.roam_score) / total_timeline_matches
            avg_spike = sum(r.biggest_spike for r in timeline_rows if r.biggest_spike) / total_timeline_matches
            avg_throw = sum(r.biggest_throw for r in timeline_rows if r.biggest_throw) / total_timeline_matches
            
            # Comeback patterns
            comeback_counts = {
                "comeback_wins": sum(1 for r in timeline_rows if r.comeback_type == "comeback"),
                "throws": sum(1 for r in timeline_rows if r.comeback_type == "throw"),
                "dominant_wins": sum(1 for r in timeline_rows if r.comeback_type == "dominated"),
                "neutral_games": sum(1 for r in timeline_rows if r.comeback_type == "neutral")
            }
            
            # Playstyle identity
            early_label = "neutral early"
            if avg_early_dom > 100:
                early_label = "strong early"
            elif avg_early_dom < -100:
                early_label = "weak early"
            
            consistency_label = "moderately consistent"
            if avg_consistency > 70:
                consistency_label = "stable"
            elif avg_consistency < 40:
                consistency_label = "coinflip"
            
            roam_label = "moderate roamer"
            if avg_roam > 3.5:
                roam_label = "heavy roamer"
            elif avg_roam < 1.5:
                roam_label = "lane anchored"
            
            playstyle_identity = {
                "early_game": early_label,
                "consistency": consistency_label,
                "roaming": roam_label
            }
            
            # Objectives
            total_objectives = {"dragon": 0, "baron": 0, "herald": 0, "tower": 0, "inhibitor": 0}
            for r in timeline_rows:
                if r.objective_presence:
                    for obj, count in r.objective_presence.items():
                        if obj in total_objectives:
                            total_objectives[obj] += count
            
            # Clean kill_positions before building cleaned_timeline (OPTION A)
            for row in timeline_rows:
                row.kill_positions = []
            
            cleaned_timeline = {
                "total_matches": total_timeline_matches,
                "average_insights": {
                    "early_dominance": round(avg_early_dom, 2),
                    "midgame_swing": round(avg_mid_swing, 2),
                    "consistency_score": round(avg_consistency, 2),
                    "roam_score": round(avg_roam, 2),
                    "biggest_spike": round(avg_spike, 2),
                    "biggest_throw": round(avg_throw, 2)
                },
                "playstyle_identity": playstyle_identity,
                "comeback_pattern": comeback_counts,
                "objectives": total_objectives
            }
            
            print(f"[RECAP] Timeline stats compiled: {total_timeline_matches} matches analyzed")
        
        # Step 4: Build Claude prompt
        print("[RECAP] Building Claude prompt...")
        prompt = f"""
You are Rift Rewind AI.

Write the recap DIRECTLY to the player in second person ("you").  
No third-person narration. Be grounded strictly in the supplied data.

RESPONSE FORMAT (STRICT JSON, NO MARKDOWN, NO BACKTICKS):
{{
  "personality_profile": string,
  "strengths": [string, string, string],
  "weaknesses": [string, string, string],
  "playstyle_summary": string,
  "actionable_tip": string,
  "fun_highlight": string
}}

RULES:
- Use only information found in STATS_DATA and TIMELINE_DATA.
- Do NOT hallucinate champions, events, or kill positions.
- Do NOT output anything except JSON that parses cleanly.
- Strengths/weaknesses must be short, punchy, data-based.
- Fun highlight must be based on themes (comeback, spike, throw), not map positions.

STATS_DATA:
{json.dumps(stats_json, indent=2)}

TIMELINE_DATA (already cleaned):
{json.dumps(cleaned_timeline, indent=2)}
"""
        
        print(f"[RECAP] Prompt length: {len(prompt)} characters")
        
        # Step 5: Call AWS Bedrock (Claude)
        print("[RECAP] Invoking AWS Bedrock Claude model...")
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        try:
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            print("[RECAP] Claude response received")
            
            # Extract the text content from Claude's response
            claude_output = response_body.get('content', [{}])[0].get('text', '')
            
            print(f"[RECAP] Claude output length: {len(claude_output)} characters")
            print("[RECAP] ==================== AI RECAP GENERATION COMPLETE ====================")
            
            # Try strict JSON parse
            try:
                recap_json = json.loads(claude_output)
            except:
                import re
                m = re.search(r"\{.*\}", claude_output, re.DOTALL)
                if m:
                    try:
                        recap_json = json.loads(m.group(0))
                    except:
                        recap_json = {"error": "Model returned invalid JSON", "raw": claude_output}
                else:
                    recap_json = {"error": "No JSON found", "raw": claude_output}
            
            return jsonify({
                "recap": recap_json,
                "stats_summary": {
                    "total_matches": total_matches,
                    "win_rate": win_rate,
                    "most_played_champion": most_played_champion
                }
            }), 200
            
        except ClientError as e:
            print(f"[RECAP] ERROR: AWS Bedrock API error: {e}")
            return jsonify({"error": "Failed to generate recap with AWS Bedrock", "details": str(e)}), 500
    
    except Exception as e:
        print(f"[RECAP] FATAL ERROR in generate_recap: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500


# Run the app
if __name__ == "__main__":
    print("Starting Rift Rewind Backend. Make sure your RIOT_API_KEY is set in a .env file.")
    app.run(debug=True)