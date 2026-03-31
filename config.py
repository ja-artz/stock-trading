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
