Rift Rewind is a Flask-based backend service that fetches, stores, and analyzes League of Legends match data using the Riot Games API. It provides long-term player analytics, role-based performance insights, extreme game statistics, monthly trends, and advanced timeline-based insights.

This backend is designed to support a data-driven frontend for player performance visualization and AI-assisted analysis.

Rift Rewind – Backend Analytics Service

Rift Rewind is a Flask-based backend service that fetches, stores, and analyzes League of Legends match data using the Riot Games API. It provides long-term player analytics, role-based performance insights, extreme game statistics, monthly trends, and advanced timeline-based insights. This backend is designed to support a data-driven frontend for player performance visualization and AI-assisted analysis.

Features
Core Match Analytics

Fetches up to 1 year of match history per player. Incremental updates ensure only new matches are fetched. Stores match data in a PostgreSQL database. Calculates win rate, KDA averages, CS per minute, kill participation, damage, gold, and vision share. Provides role-based performance and impact analysis along with champion and game mode distributions.

Advanced Insights

Identifies extreme games including best and worst KDA performances, highest damage, CS, deaths, assists, fastest games, and longest games. Provides monthly performance trends such as win rate, champion pool changes, role usage, and impact metrics over time.

Timeline Analysis System

Processes Riot match timeline data to extract early game dominance, midgame swing potential, consistency scores, level 6/11/16 timing, gold advantage swings, roaming behavior, kill locations, and objective participation. Timeline insights are stored in a dedicated analytics table for visualization and AI usage.

Scalable and Production-Oriented

Uses async API requests via aiohttp, rate-limit-aware retries with exponential backoff, batched database inserts using psycopg2.execute_values, database connection health checks, and CORS support for frontend integration.

Tech Stack

Backend Framework: Flask
Async Networking: aiohttp, asyncio
Database: PostgreSQL
ORM: SQLAlchemy, Flask-Migrate
External APIs: Riot Games API, AWS Bedrock (Claude 3 Haiku)
Infrastructure: dotenv, boto3
Data Processing: Python, SQL

Project Structure

app.py
.env
migrations/
Key Models:
Match – Stores per-match player statistics
MatchTimelineSummary – Stores aggregated timeline insights

Environment Variables

Create a .env file in the root directory:
RIOT_API_KEY=your_riot_api_key
DATABASE_URL=postgresql://user:password@host:port/dbname
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_REGION=us-east-1

Running the Server

pip install -r requirements.txt
flask db upgrade
python app.py
The server will run at http://localhost:5000
