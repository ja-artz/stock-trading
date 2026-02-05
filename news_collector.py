"""News collection module for gathering news from Google News RSS feed."""

import feedparser
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import quote
import time


class NewsCollector:
    """Collects news articles from Google News RSS feed."""
    
    def __init__(self, rss_url: str, max_age_hours: int = 24):
        """
        Initialize the news collector.
        
        Args:
            rss_url: URL of the Google News RSS feed
            max_age_hours: Maximum age of news articles to collect (in hours)
        """
        self.rss_url = rss_url
        self.max_age_hours = max_age_hours
    
    def fetch_news(self, query: Optional[str] = None, num_results: int = 20) -> List[Dict]:
        """
        Fetch news articles from Google News.
        
        Args:
            query: Optional search query (if None, uses default RSS feed)
            num_results: Maximum number of results to fetch
            
        Returns:
            List of news article dictionaries with title, link, published, summary
        """
        # Build RSS URL with query if provided
        if query:
            # URL encode the query to handle spaces and special characters
            encoded_query = quote(query, safe='')
            # Google News RSS format
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        else:
            rss_url = self.rss_url
        
        try:
            # Parse RSS feed
            feed = feedparser.parse(rss_url)
            
            articles = []
            cutoff_time = datetime.now() - timedelta(hours=self.max_age_hours)
            
            for entry in feed.entries[:num_results]:
                # Parse published date
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        # Type ignore: feedparser returns time.struct_time which is compatible
                        parsed_time = entry.published_parsed[:6]  # type: ignore
                        published_time = datetime(*parsed_time)
                    except (TypeError, ValueError, IndexError):
                        continue
                else:
                    continue
                
                # Filter by age if max_age_hours is set
                if self.max_age_hours > 0 and published_time < cutoff_time:
                    continue
                
                # Extract source from entry (feedparser provides source info)
                source = self._extract_source(entry)
                
                # Get title and summary as strings
                title = str(entry.get('title', '')) if entry.get('title') else ''
                summary_raw = entry.get('summary', '')
                summary = self._clean_summary(str(summary_raw) if summary_raw else '')
                
                # Extract clean title (remove source suffix if present)
                # Google News titles often have " - Source" at the end, remove it
                if ' - ' in title and source and title.endswith(source):
                    title = title.rsplit(' - ', 1)[0]
                
                # Extract article data
                article = {
                    'title': title,
                    'link': str(entry.get('link', '')) if entry.get('link') else '',
                    'published': published_time.isoformat(),
                    'published_parsed': entry.published_parsed,
                    'summary': summary,
                    'source': source
                }
                
                # Try to get full article content if summary is missing
                if not article['summary']:
                    article['summary'] = self._fetch_article_content(article['link'])
                
                articles.append(article)
            
            return articles
        
        except Exception as e:
            print(f"Error fetching news: {e}")
            return []
    
    def _extract_source(self, entry) -> str:
        """Extract source name from feed entry."""
        try:
            # Try to get source from entry's source field
            if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
                return entry.source.title
            
            # Try to extract from title (Google News format: "Title - Source")
            title = entry.get('title', '')
            if ' - ' in title:
                parts = title.rsplit(' - ', 1)
                if len(parts) == 2:
                    return parts[1].strip()
            
            # Fallback: try to extract from link domain
            link = entry.get('link', '')
            if link and 'news.google.com' not in link:
                # Try to get domain from actual article URL
                from urllib.parse import urlparse
                parsed = urlparse(link)
                domain = parsed.netloc
                # Remove www. prefix and get main domain
                if domain.startswith('www.'):
                    domain = domain[4:]
                # Get just the domain name (e.g., 'bbc.com' -> 'BBC')
                domain_parts = domain.split('.')
                if len(domain_parts) >= 2:
                    return domain_parts[0].upper() if len(domain_parts[0]) <= 5 else domain_parts[0].title()
                return domain.title()
            
            return 'Unknown'
        except:
            return 'Unknown'
    
    def _clean_summary(self, summary: str) -> str:
        """Clean HTML from summary and extract plain text."""
        if not summary:
            return ''
        
        try:
            # Parse HTML and extract text
            soup = BeautifulSoup(summary, 'html.parser')
            # Get text content
            text = soup.get_text(separator=' ', strip=True)
            # Clean up extra whitespace
            text = ' '.join(text.split())
            return text
        except:
            # If parsing fails, try simple string replacement
            # Remove common HTML tags
            import re
            text = re.sub(r'<[^>]+>', '', summary)
            text = ' '.join(text.split())
            return text
    
    def _fetch_article_content(self, url: str, timeout: int = 5) -> str:
        """
        Attempt to fetch article content from URL.
        This is a simple implementation - can be enhanced later.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=timeout)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try to extract main content
            # This is basic - can be improved with newspaper3k or similar
            paragraphs = soup.find_all('p')
            content = ' '.join([p.get_text() for p in paragraphs[:5]])  # First 5 paragraphs
            return content[:500]  # Limit to 500 chars
        except:
            return ''
    
    def get_general_news(self, num_results: int = 20) -> List[Dict]:
        """
        Get general news articles from Google News top stories.
        
        Args:
            num_results: Maximum number of results
            
        Returns:
            List of news articles
        """
        # Use Google News top stories RSS (no query = general news)
        return self.fetch_news(query=None, num_results=num_results)


if __name__ == "__main__":
    # Test the news collector
    collector = NewsCollector(
        rss_url="https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    )
    
    articles = collector.get_general_news(num_results=10)
    print(f"Found {len(articles)} articles")
    
    for i, article in enumerate(articles[:3], 1):
        print(f"\n{i}. {article['title']}")
        print(f"   Source: {article['source']}")
        print(f"   Published: {article['published']}")
        print(f"   Link: {article['link']}")
