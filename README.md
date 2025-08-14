# TenderBot

## Setup
1) Python 3.10+
2) pip install -r requirements.txt
3) playwright install  # and playwright install-deps on Linux
4) Copy .env from template and fill in keys
5) Create table in Supabase SQL editor using DDL in services/db.py (CREATE_TENDERS_SQL)

## Run
# one-shot
python tenderbot.py

# loop every 6h
python tenderbot.py --loop 21600

# check/init db connectivity
python tenderbot.py --init-db
