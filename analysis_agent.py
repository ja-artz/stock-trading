"""Analysis agent that uses LLM to analyze news stories and generate trading recommendations."""

from typing import List, Dict
from anthropic import Anthropic
import json
import config


class AnalysisAgent:
    """LLM agent that analyzes news stories and generates trading recommendations."""
    
    def __init__(self):
        """Initialize the analysis agent with Claude API."""
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
    
    def analyze_story(self, article: Dict) -> Dict:
        """
        Analyze a single news story and generate trading recommendations.
        
        Args:
            article: News article dictionary with title, summary, link, etc.
            
        Returns:
            Dictionary with analysis and recommendations
        """
        prompt = f"""You are a financial analyst specializing in event-driven trading strategies. Analyze this news story and provide trading recommendations for US stocks and options.

News Story:
Title: {article.get('title', 'N/A')}
Source: {article.get('source', 'Unknown')}
Published: {article.get('published', 'Unknown')}
Summary: {article.get('summary', 'No summary available')}
Link: {article.get('link', '')}

Provide a concise but comprehensive analysis in the following JSON format.
Keep free-text fields reasonably short (e.g., thesis under 200 words) and limit lists to at most 5 items each:

{{
    "catalyst_type": "M&A|regulatory|geopolitical|earnings|product_launch|management_change|other",
    "timeline": "1-4_weeks|1-6_months|6-12_months|12+_months",
    "risk_level": 1-10,
    "affected_companies": [
        {{
            "ticker": "SYMBOL",
            "company_name": "Full Company Name",
            "impact_type": "primary|secondary|tertiary",
            "expected_direction": "bullish|bearish|neutral",
            "confidence": 1-10
        }}
    ],
    "thesis": "Detailed explanation of why this news creates a trading opportunity",
    "recommended_tier": 1|2|3|4,
    "expected_return_range": "X% to Y%",
    "key_milestones": ["Milestone 1", "Milestone 2"],
    "recommendations": [
        {{
            "ticker": "SYMBOL",
            "instrument_type": "stock|call_option|put_option",
            "recommended_tier": 1|2|3|4,
            "allocation_percent": "X% of tier",
            "rationale": "Why this specific position",
            "entry_trigger": "When to enter",
            "exit_trigger": "When to exit",
            "stop_loss": "Stop loss level if applicable"
        }}
    ],
    "risks": ["Risk 1", "Risk 2"],
    "alternative_plays": ["Alternative opportunity 1", "Alternative opportunity 2"]
}}

Important guidelines:
- Only recommend US-listed stocks and options
- Verify ticker symbols are correct (use standard format like AAPL, not APPL)
- Be specific about catalyst timing
- Consider both direct and indirect effects (second-order impacts)
- If no clear trading opportunity exists, set recommendations to empty array
- Risk level: 1-3 (low), 4-6 (medium), 7-10 (high)
- Recommended tier: 1 (quick strike, 28 days), 2 (medium-term, 1-6 months), 3 (long-term, 6-12 months), 4 (speculative)

Return only valid JSON, no markdown formatting or additional text."""

        try:
            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            # Parse response
            response_text = message.content[0].text.strip()

            # Extract JSON from response (handle markdown code blocks if present)
            if "```json" in response_text:
                response_text = response_text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```", 1)[1].split("```", 1)[0].strip()

            # Try to parse JSON, with a fallback that trims to the last complete brace
            try:
                analysis = json.loads(response_text)
            except json.JSONDecodeError:
                # Attempt to recover by trimming to the last closing brace
                first_brace = response_text.find("{")
                last_brace = response_text.rfind("}")
                recovered = None
                while first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    candidate = response_text[first_brace:last_brace + 1]
                    try:
                        recovered = json.loads(candidate)
                        break
                    except json.JSONDecodeError:
                        last_brace = response_text.rfind("}", 0, last_brace)

                if recovered is None:
                    # Re-raise to be handled by the outer json error handler
                    raise

                analysis = recovered
            
            # Add article metadata to analysis
            analysis['article_title'] = article.get('title', '')
            analysis['article_link'] = article.get('link', '')
            analysis['article_published'] = article.get('published', '')
            
            return analysis
        
        except json.JSONDecodeError as e:
            print(f"Error parsing analysis JSON: {e}")
            print(f"Response was: {response_text[:500]}")
            return {
                "error": "Failed to parse analysis",
                "raw_response": response_text[:500],
                "article_title": article.get('title', '')
            }
        
        except Exception as e:
            print(f"Error in analysis agent: {e}")
            return {
                "error": str(e),
                "article_title": article.get('title', '')
            }
    
    def analyze_stories(self, articles: List[Dict]) -> List[Dict]:
        """
        Analyze multiple news stories.
        
        Args:
            articles: List of news article dictionaries
            
        Returns:
            List of analysis dictionaries
        """
        analyses = []
        for i, article in enumerate(articles, 1):
            print(f"\nAnalyzing story {i}/{len(articles)}: {article.get('title', 'Unknown')[:60]}...")
            analysis = self.analyze_story(article)
            analyses.append(analysis)
        
        return analyses


if __name__ == "__main__":
    # Test the analysis agent
    test_article = {
        'title': 'Example: Major Tech Company Announces Merger',
        'summary': 'A major technology company has announced plans to merge with a competitor, potentially reshaping the industry landscape.',
        'source': 'Financial Times',
        'published': '2025-01-15T10:00:00',
        'link': 'https://example.com/news'
    }
    
    agent = AnalysisAgent()
    analysis = agent.analyze_story(test_article)
    
    print("\nAnalysis Result:")
    print(json.dumps(analysis, indent=2))
