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

# LLM Settings
ANTHROPIC_MODEL = "claude-sonnet-5-20250219"  # Claude Sonnet 5
OPENAI_MODEL = "gpt-5-mini"  # Fallback or for structured data

# Analysis Settings
FOCUS_MARKETS = "US stocks and options"
MIN_NEWS_AGE_HOURS = 0  # How old news can be (0 = any)
MAX_NEWS_AGE_HOURS = 24  # Maximum age of news to consider
