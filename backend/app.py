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

# Explicitly specify the .env file path to ensure it's loaded correctly
load_dotenv(dotenv_path=".env")

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Riot API key (Reminder: Store this in a .env file for security!)
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "RGAPI-ab034026-0b86-4bc1-9d26-90762153f017")

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

# Define database models
class Match(db.Model):
    id = db.Column(db.String, primary_key=True)
    game_mode = db.Column(db.String, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    champion = db.Column(db.String, nullable=False)
    kda = db.Column(db.String, nullable=False)
    win = db.Column(db.Boolean, nullable=False)
    puuid = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.BigInteger, nullable=False, index=True)  # New column to store match start time

# Add other models as needed

# Root endpoint
@app.route("/")
def home():
    """Returns a status message indicating the backend is online."""
    return jsonify({"status": "Rift Rewind Backend Online"})

# Updated `/get-stats` endpoint for incremental fetching
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

            # Step 2: Determine the start time for fetching matches
            # Updated start_time to fetch from the last match in the database
            # Ensure `start_time` defaults to January 1, 2025, for new players
            last_match = Match.query.filter_by(puuid=puuid).order_by(Match.timestamp.desc()).first()
            start_time = int(datetime(2025, 1, 1).timestamp()) if not last_match else int(last_match.timestamp / 1000)

            # Step 3: Fetch match IDs incrementally
            matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
            match_ids = []
            start = 0

            async def fetch_match_ids(start):
                paginated_url = f"{matches_url}?startTime={start_time}&start={start}&count=100"
                retries = 0
                while retries < 5:  # Retry up to 5 times
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
            existing_ids = {m.id for m in Match.query.filter(Match.id.in_(match_ids)).all()}
            print(f"Existing match IDs in database: {len(existing_ids)}")
            new_ids = [mid for mid in match_ids if mid not in existing_ids]
            print(f"New match IDs to fetch details for: {len(new_ids)}")

            # Define the detail fetcher
            async def fetch_match_details(match_id, session, puuid):
                match_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}"
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
                        participant = next((p for p in info.get("participants", []) if p["puuid"] == puuid), None)
                        if not participant:
                            print(f"No participant for {puuid} in match {match_id}")
                            return None
                        return Match(
                            id=match_id,
                            game_mode=info.get("gameMode", "UNKNOWN"),
                            duration=info.get("gameDuration", 0),
                            champion=participant.get("championName", "Unknown"),
                            kda=f"{participant.get('kills',0)}/{participant.get('deaths',0)}/{participant.get('assists',0)}",
                            win=participant.get("win", False),
                            puuid=puuid,
                            timestamp=info.get("gameStartTimestamp", 0)
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

                        # Convert batch to a list of tuples for execute_values
                        values = [
                            (
                                match.id,
                                match.game_mode,
                                match.duration,
                                match.champion,
                                match.kda,
                                match.win,
                                match.puuid,
                                match.timestamp
                            ) for match in batch
                        ]

                        # Retry logic for database insertion
                        retries = 3
                        while retries > 0:
                            try:
                                conn = db.engine.raw_connection()
                                try:
                                    with conn.cursor() as cursor:
                                        execute_values(
                                            cursor,
                                            """
                                            INSERT INTO match (id, game_mode, duration, champion, kda, win, puuid, timestamp)
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
                except Exception as e:
                    print(f"Error inserting matches into the database: {e}")

            # Step 6: Combine all matches (existing + new) and generate insights
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
            total_losses = total_matches - total_wins
            total_kills = 0
            total_deaths = 0
            total_assists = 0
            champion_count = defaultdict(int)
            game_mode_count = defaultdict(int)

            for match in all_matches:
                try:
                    kills, deaths, assists = map(int, match.kda.split("/"))
                    total_kills += kills
                    total_deaths += deaths
                    total_assists += assists
                    champion_count[match.champion] += 1
                    game_mode_count[match.game_mode] += 1
                except ValueError:
                    print(f"Invalid KDA format for match {match.id}: {match.kda}")

            avg_kills = total_kills / total_matches
            avg_deaths = total_deaths / total_matches
            avg_assists = total_assists / total_matches
            win_rate = (total_wins / total_matches) * 100

            most_played_champion = max(champion_count, key=champion_count.get, default="Unknown")

            return jsonify({
                "gameName": game_name,
                "tagLine": tag_line,
                "puuid": puuid,
                "total_matches": total_matches,
                "total_wins": total_wins,
                "total_losses": total_losses,
                "win_rate": f"{win_rate:.2f}",
                "average_kda": {
                    "kills": f"{avg_kills:.2f}",
                    "deaths": f"{avg_deaths:.2f}",
                    "assists": f"{avg_assists:.2f}"
                },
                "most_played_champion": most_played_champion,
                "game_mode_distribution": dict(game_mode_count)
            })

    except aiohttp.ClientError as e:
        return jsonify({"error": "An error occurred while communicating with the Riot Games API.", "details": str(e)}), 500

    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500

# Run the app
if __name__ == "__main__":
    print("Starting Rift Rewind Backend. Make sure your RIOT_API_KEY is set in a .env file.")
    app.run(debug=True)
