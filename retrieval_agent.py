"""Retrieval agent that selects stories for downstream analysis."""

from typing import List, Dict, Optional, Literal
from agents import Agent, Runner, function_tool
from news_collector import NewsCollector
import json
import config

RetrievalMode = Literal["headline", "upside"]


class RetrievalAgent:
    """LLM retrieval agent with mode-specific selection behavior."""

    INSTRUCTIONS_BY_MODE = {
        "headline": """You are a financial news selector focused on major market-moving headlines.

Select stories that are likely to drive broad US market movement or major sector repricing.
Prioritize high-visibility developments such as:
- Central bank, inflation, or labor macro releases
- Geopolitical and policy shifts
- Earnings surprises, guidance shocks, and major corporate actions
- Regulatory announcements with near-term market impact
- Material commodity, rates, or FX catalysts

Avoid niche stories unless they are clearly market-moving.

Return a JSON object with:
- "articles": array of selected articles, each with "title", "source", and "summary"
- "reasoning": brief explanation

Return JSON only, no markdown.""",
        "upside": """You are a financial news selector focused on non-headline, high-upside opportunities.

Select stories that are NOT likely to be front-page headlines but could create asymmetric upside/downside if validated.
Prioritize under-the-radar catalysts such as:
- Early supply-chain signals
- Small policy/regulatory changes with second-order impact
- Emerging technology or product milestones
- Smaller company developments that can propagate to larger listed names
- Industry-specific inflections not yet fully priced by broad sentiment

Do NOT perform full trading recommendation analysis. Your job is only to surface promising candidate stories.

Return a JSON object with:
- "articles": array of selected articles, each with "title", "source", and "summary"
- "reasoning": brief explanation

Return JSON only, no markdown."""
    }
    
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
        
        self.agents = {
            mode: Agent(
                name=f"Retrieval Agent ({mode})",
                instructions=instructions,
                tools=[self.fetch_news_tool],
                model=self.model
            )
            for mode, instructions in self.INSTRUCTIONS_BY_MODE.items()
        }
    
    async def select_top_stories(
        self, 
        mode: RetrievalMode = "headline",
        news_articles: Optional[List[Dict]] = None,
        query: Optional[str] = None,
        num_results: int = 20,
        min_stories: int = 3,
        max_stories: int = 5
    ) -> Dict:
        """
        Use LLM agent to fetch and select the most relevant news stories for trading analysis.
        
        Args:
            news_articles: Optional list of news article dictionaries. If None, will fetch news using the tool.
            query: Optional search query to filter news (only used if news_articles is None)
            num_results: Number of articles to fetch (only used if news_articles is None)
            mode: Retrieval mode ("headline" or "upside")
            max_stories: Maximum number of stories to select
            
        Returns:
            Dictionary with "articles" (list of {title, source, summary}) and "reasoning" (str)
        """
        if mode not in self.agents:
            raise ValueError(f"Unsupported retrieval mode: {mode}")
        max_stories = max(min_stories, max_stories)

        if news_articles is not None:
            if not news_articles:
                return {"articles": [], "reasoning": "No articles provided"}
            
            # Prepare articles for LLM
            articles_text = self._format_articles_for_llm(news_articles)
            
            # Create user prompt with just the articles and selection request
            user_prompt = f"""Here are {len(news_articles)} news articles to choose from:

{articles_text}

Select between {min_stories} and {max_stories} articles based on the retrieval mode objective.

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
            user_prompt = f"""Fetch recent news articles using the fetch_news_from_rss tool. 
If you need to search for specific topics, use the query parameter (e.g., "stock market", "technology", "politics").
Fetch at least {num_results} articles, then select between {min_stories} and {max_stories} articles that best fit the retrieval mode objective.

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
            result = await Runner.run(self.agents[mode], user_prompt)
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
            
            if len(formatted_articles) < min_stories and news_articles:
                seen_titles = {a.get("title", "") for a in formatted_articles}
                for article in news_articles:
                    title = article.get("title", "")
                    if title and title not in seen_titles:
                        formatted_articles.append(
                            {
                                "title": title,
                                "source": article.get("source", "Unknown"),
                                "summary": article.get("summary", "")
                            }
                        )
                        seen_titles.add(title)
                    if len(formatted_articles) >= min_stories:
                        break

            print(f"Retrieval Agent ({mode}) Reasoning: {reasoning}")
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
