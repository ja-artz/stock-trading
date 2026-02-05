"""Retrieval agent that uses LLM to select the most relevant news stories for analysis."""

from typing import List, Dict, Optional
from agents import Agent, Runner, function_tool
from news_collector import NewsCollector
import json
import config


class RetrievalAgent:
    """LLM agent that selects top news stories for trading analysis using the agents library."""
    
    INSTRUCTIONS = """You are a financial analyst selecting news stories that could create trading opportunities in US stocks and options.

Your goal is to identify ANY news stories that could impact markets, including:
- Direct financial news (M&A, earnings, regulatory actions, policy changes)
- Geopolitical events (wars, elections, trade disputes, sanctions)
- Economic developments (inflation, interest rates, employment)
- Technology breakthroughs or disruptions
- Natural disasters or supply chain disruptions
- Social/political events that affect industries
- Company-specific news (product launches, management changes, partnerships)
- Sector-wide developments
- Second-order effects (e.g., geopolitical event → commodity prices → related stocks)

Focus on stories that:
1. Could impact publicly traded US companies (directly or indirectly)
2. Are recent and timely (within last 24 hours preferred)
3. Have sufficient detail to analyze potential market implications
4. Have clear causal relationships to market movements

You have access to a tool called fetch_news_from_rss that can retrieve real-time news from Google News RSS feeds.
You can use this tool to fetch news articles, then analyze and select the most relevant ones.

When selecting articles, return your selection as a JSON object with:
- "articles": array of selected articles, each with "title", "source", and "summary" fields
- "reasoning": brief explanation of why these articles were selected

The articles array should be in this format:
[
    {
        "source": "source name",
        "title": "article title",
        "summary": "article summary"
    }
]

Format your response as JSON only, no markdown or additional text."""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Initialize the retrieval agent.
        
        Args:
            model: Model to use for the agent (default: "gpt-4o-mini")
        """
        self.model = model
        self.news_collector = NewsCollector(
            rss_url=config.GOOGLE_NEWS_RSS_URL,
            max_age_hours=config.MAX_NEWS_AGE_HOURS
        )
        
        # Create the tool for fetching news
        @function_tool
        def fetch_news_from_rss(query: Optional[str] = None, num_results: int = 20) -> List[Dict]:
            """
            Fetch news articles from Google News RSS feed.
            
            Args:
                query: Optional search query to filter news (e.g., "stock market", "technology"). 
                       If None, fetches general top news stories.
                num_results: Maximum number of articles to fetch (default: 20, max recommended: 50)
            
            Returns:
                List of news article dictionaries, each containing:
                - title: Article headline
                - source: News source name
                - link: URL to the full article
                - published: Publication date in ISO format
                - summary: Article summary or excerpt
            """
            articles = self.news_collector.fetch_news(query=query, num_results=num_results)
            return articles
        
        self.fetch_news_tool = fetch_news_from_rss
        
        # Create the agent with the tool
        self.agent = Agent(
            name="Retrieval Agent",
            instructions=self.INSTRUCTIONS,
            tools=[self.fetch_news_tool],
            model=self.model
        )
    
    async def select_top_stories(
        self, 
        news_articles: Optional[List[Dict]] = None,
        query: Optional[str] = None,
        num_results: int = 20,
        max_stories: int = 3
    ) -> Dict:
        """
        Use LLM agent to fetch and select the most relevant news stories for trading analysis.
        
        Args:
            news_articles: Optional list of news article dictionaries. If None, will fetch news using the tool.
            query: Optional search query to filter news (only used if news_articles is None)
            num_results: Number of articles to fetch (only used if news_articles is None)
            max_stories: Maximum number of stories to select
            
        Returns:
            Dictionary with "articles" (list of {title, source, summary}) and "reasoning" (str)
        """
        # If articles are provided, use them directly
        if news_articles is not None:
            if not news_articles:
                return {"articles": [], "reasoning": "No articles provided"}
            
            # Prepare articles for LLM
            articles_text = self._format_articles_for_llm(news_articles)
            
            # Create user prompt with just the articles and selection request
            user_prompt = f"""Here are {len(news_articles)} news articles to choose from:

{articles_text}

Select exactly {max_stories} articles that are most relevant for generating trading recommendations.

Return your selection as a JSON object with:
- "articles": array of selected articles, each with "title", "source", and "summary" fields
- "reasoning": brief explanation of why these articles were selected

The articles array should be in this format:
[
    {{
        "source": "source name",
        "title": "article title",
        "summary": "article summary"
    }}
]

Format your response as JSON only, no markdown or additional text."""
        else:
            # Use the agent to fetch and select news
            user_prompt = f"""Fetch recent news articles using the fetch_news_from_rss tool. 
If you need to search for specific topics, use the query parameter (e.g., "stock market", "technology", "politics").
Fetch at least {num_results} articles, then analyze them and select the top {max_stories} articles that are most relevant for generating trading recommendations.

After fetching and analyzing the articles, return your selection as a JSON object with:
- "articles": array of selected articles, each with "title", "source", and "summary" fields
- "reasoning": brief explanation of why these articles were selected

The articles array should be in this format:
[
    {{
        "source": "source name",
        "title": "article title",
        "summary": "article summary"
    }}
]

Format your response as JSON only, no markdown or additional text."""

        try:
            # Run the agent
            result = await Runner.run(self.agent, user_prompt)
            response_text = result.final_output.strip()
            
            # Extract JSON from response (handle markdown code blocks if present)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result_json = json.loads(response_text)
            reasoning = result_json.get("reasoning", "")
            articles = result_json.get("articles", [])
            
            # Validate and format articles to ensure they have the required fields
            formatted_articles = []
            for article in articles[:max_stories]:
                if isinstance(article, dict):
                    formatted_article = {
                        "title": article.get("title", ""),
                        "source": article.get("source", "Unknown"),
                        "summary": article.get("summary", "")
                    }
                    formatted_articles.append(formatted_article)
            
            print(f"Retrieval Agent Reasoning: {reasoning}")
            print(f"Selected {len(formatted_articles)} articles for analysis\n")
            
            return {
                "articles": formatted_articles,
                "reasoning": reasoning
            }
        
        except json.JSONDecodeError as e:
            print(f"Error parsing LLM response: {e}")
            print(f"Response was: {response_text}")
            # Fallback: return first N articles in the expected format
            if news_articles is None:
                fetched_articles = self.news_collector.fetch_news(query=query, num_results=num_results)
                fallback_articles = fetched_articles[:max_stories]
            else:
                fallback_articles = news_articles[:max_stories] if news_articles else []
            
            formatted_fallback = [
                {
                    "title": article.get("title", ""),
                    "source": article.get("source", "Unknown"),
                    "summary": article.get("summary", "")
                }
                for article in fallback_articles
            ]
            return {
                "articles": formatted_fallback,
                "reasoning": "Error parsing response, returned first articles as fallback"
            }
        
        except Exception as e:
            print(f"Error in retrieval agent: {e}")
            # Fallback: return first N articles in the expected format
            if news_articles is None:
                fetched_articles = self.news_collector.fetch_news(query=query, num_results=num_results)
                fallback_articles = fetched_articles[:max_stories]
            else:
                fallback_articles = news_articles[:max_stories] if news_articles else []
            
            formatted_fallback = [
                {
                    "title": article.get("title", ""),
                    "source": article.get("source", "Unknown"),
                    "summary": article.get("summary", "")
                }
                for article in fallback_articles
            ]
            return {
                "articles": formatted_fallback,
                "reasoning": f"Error occurred: {str(e)}"
            }
    
    def _format_articles_for_llm(self, articles: List[Dict]) -> str:
        """Format articles for LLM input."""
        formatted = []
        for i, article in enumerate(articles):
            formatted.append(
                f"[{i}] {article['title']}\n"
                f"    Source: {article.get('source', 'Unknown')}\n"
                f"    Published: {article.get('published', 'Unknown')}\n"
                f"    Summary: {article.get('summary', 'No summary available')[:300]}\n"
                f"    Link: {article.get('link', '')}\n"
            )
        return "\n".join(formatted)


if __name__ == "__main__":
    # Test the retrieval agent
    import asyncio
    
    async def test_agent():
        agent = RetrievalAgent()
        
        # Test 1: Fetch and select news using the tool
        print("Test 1: Fetching and selecting news using the tool...")
        result = await agent.select_top_stories(
            query=None,  # General news
            num_results=15,
            max_stories=3
        )
        
        print(f"\nReasoning: {result['reasoning']}")
        print(f"\nSelected {len(result['articles'])} articles:")
        for i, article in enumerate(result['articles'], 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Source: {article['source']}")
            print(f"   Summary: {article['summary'][:150]}..." if len(article['summary']) > 150 else f"   Summary: {article['summary']}")
        
        # Test 2: Select from provided articles
        print("\n" + "="*80)
        print("Test 2: Selecting from provided articles...")
        articles = agent.news_collector.get_general_news(num_results=10)
        print(f"Collected {len(articles)} articles\n")
        
        result2 = await agent.select_top_stories(
            news_articles=articles,
            max_stories=3
        )
        
        print(f"\nReasoning: {result2['reasoning']}")
        print(f"\nSelected {len(result2['articles'])} articles:")
        for i, article in enumerate(result2['articles'], 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Source: {article['source']}")
            print(f"   Summary: {article['summary'][:150]}..." if len(article['summary']) > 150 else f"   Summary: {article['summary']}")
    
    asyncio.run(test_agent())
