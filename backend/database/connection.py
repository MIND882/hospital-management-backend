# database/connection.py - COPY EXACT YE CODE
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from urllib.parse import quote_plus

load_dotenv()

# HARDCODE - NO .env confusion
DB_USER = "medicare_admin"
DB_PASS = "CHAUHAN@55@123"  # Tumhara password
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "medicare"

# URL ENCODE PASSWORD
encoded_pass = quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{encoded_pass}@{DB_HOST}:{DB_PORT}/{DB_NAME}"



engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
