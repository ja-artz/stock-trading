"""Configuration settings for the trading system."""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# News Collection Settings
MAX_STORIES_TO_ANALYZE = 5
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"  # General news feed
NEWS_FETCH_POOL_SIZE = 30
RETRIEVAL_MIN_STORIES_PER_AGENT = 3
RETRIEVAL_MAX_STORIES_PER_AGENT = 5
ACTIONABLE_STORIES_TO_ANALYZE = 5

# Multi-persona analysis (aggressive, moderate, minimal risk)
ANALYST_PROFILES = ("aggressive", "moderate", "minimal_risk")

# LLM Settings
# Use a current, supported Anthropic Claude model ID
# Latest balanced model as of March 2026
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # Claude Sonnet 4.6
# Retries for transient Anthropic errors (e.g. 529 overloaded, 429, 5xx)
ANTHROPIC_MAX_RETRIES = 6
ANTHROPIC_RETRY_BASE_DELAY_SEC = 2.0
OPENAI_MODEL = "gpt-5-mini"  # Fallback or for structured data

# Analysis Settings
FOCUS_MARKETS = "US stocks and options"
MIN_NEWS_AGE_HOURS = 0  # How old news can be (0 = any)
MAX_NEWS_AGE_HOURS = 24  # Maximum age of news to consider

# Validation (no paid market-data API keys; uses HTTP + yfinance)
VALIDATION_URL_TIMEOUT = 8
# When ticker checks fail, ask the analysis LLM to rewrite the envelope once
ENABLE_TICKER_REFINEMENT_LOOP = True

# Indirect (2nd/3rd order) effects analysis for non-market-direct stories
ENABLE_INDIRECT_EFFECTS_ANALYSIS = True
INDIRECT_MAX_CHAINS = 3
TRADER_MAX_INDIRECT_ITEMS_PER_PLAN = 1
INDIRECT_MIN_CONFIDENCE_FOR_BUY = 6

# Persistence
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
DATA_DIR = os.getenv("DATA_DIR", "data")
EXPORT_DIR = os.getenv("EXPORT_DIR", "data/exports")

# API / household
HOUSEHOLD_API_KEY = os.getenv("HOUSEHOLD_API_KEY", "")
HOUSEHOLD_NAME = os.getenv("HOUSEHOLD_NAME", "Our Household")
MEMBER_1_NAME = os.getenv("MEMBER_1_NAME", "Member 1")
MEMBER_2_NAME = os.getenv("MEMBER_2_NAME", "Member 2")
INITIAL_CASH = float(os.getenv("INITIAL_CASH", "1000"))
