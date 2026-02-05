"""Main orchestration script for the trading recommendation system."""

import json
import asyncio
from datetime import datetime
from news_collector import NewsCollector
from retrieval_agent import RetrievalAgent
from analysis_agent import AnalysisAgent
import config


def format_recommendations(analyses: list) -> str:
    """Format analysis results for display."""
    output = []
    output.append("=" * 80)
    output.append("TRADING RECOMMENDATIONS")
    output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append("=" * 80)
    
    for i, analysis in enumerate(analyses, 1):
        if "error" in analysis:
            output.append(f"\n[ERROR] Story {i}: {analysis.get('article_title', 'Unknown')}")
            output.append(f"Error: {analysis.get('error', 'Unknown error')}")
            continue
        
        output.append(f"\n{'='*80}")
        output.append(f"STORY {i}: {analysis.get('article_title', 'Unknown')}")
        output.append(f"{'='*80}")
        output.append(f"Catalyst Type: {analysis.get('catalyst_type', 'N/A')}")
        output.append(f"Timeline: {analysis.get('timeline', 'N/A')}")
        output.append(f"Risk Level: {analysis.get('risk_level', 'N/A')}/10")
        output.append(f"Recommended Tier: {analysis.get('recommended_tier', 'N/A')}")
        output.append(f"Expected Return: {analysis.get('expected_return_range', 'N/A')}")
        
        output.append(f"\nThesis:")
        output.append(f"  {analysis.get('thesis', 'N/A')}")
        
        # Affected companies
        affected = analysis.get('affected_companies', [])
        if affected:
            output.append(f"\nAffected Companies:")
            for company in affected:
                output.append(f"  - {company.get('ticker', 'N/A')} ({company.get('company_name', 'N/A')})")
                output.append(f"    Impact: {company.get('impact_type', 'N/A')}, Direction: {company.get('expected_direction', 'N/A')}")
        
        # Recommendations
        recommendations = analysis.get('recommendations', [])
        if recommendations:
            output.append(f"\nTrading Recommendations:")
            for j, rec in enumerate(recommendations, 1):
                output.append(f"\n  {j}. {rec.get('ticker', 'N/A')} - {rec.get('instrument_type', 'N/A')}")
                output.append(f"     Tier: {rec.get('recommended_tier', 'N/A')}, Allocation: {rec.get('allocation_percent', 'N/A')}")
                output.append(f"     Rationale: {rec.get('rationale', 'N/A')}")
                output.append(f"     Entry: {rec.get('entry_trigger', 'N/A')}")
                output.append(f"     Exit: {rec.get('exit_trigger', 'N/A')}")
                if rec.get('stop_loss'):
                    output.append(f"     Stop Loss: {rec.get('stop_loss')}")
        else:
            output.append(f"\nNo specific recommendations generated for this story.")
        
        # Risks
        risks = analysis.get('risks', [])
        if risks:
            output.append(f"\nRisks:")
            for risk in risks:
                output.append(f"  - {risk}")
        
        # Key milestones
        milestones = analysis.get('key_milestones', [])
        if milestones:
            output.append(f"\nKey Milestones to Watch:")
            for milestone in milestones:
                output.append(f"  - {milestone}")
    
    return "\n".join(output)


def save_results(analyses: list, filename: str = None):
    """Save analysis results to JSON file."""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recommendations_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(analyses, f, indent=2)
    
    print(f"\nResults saved to: {filename}")


async def main():
    """Main execution function."""
    print("=" * 80)
    print("STOCK TRADING RECOMMENDATION SYSTEM - MVP")
    print("=" * 80)
    print()
    
    # Step 1: Collect news (optional - can also let retrieval agent fetch directly)
    print("Step 1: Collecting news...")
    collector = NewsCollector(
        rss_url=config.GOOGLE_NEWS_RSS_URL,
        max_age_hours=config.MAX_NEWS_AGE_HOURS
    )
    
    articles = collector.get_general_news(num_results=20)
    print(f"Collected {len(articles)} news articles")
    
    if not articles:
        print("No articles found. Exiting.")
        return
    
    # Step 2: Select top stories using retrieval agent
    print(f"\nStep 2: Selecting top {config.MAX_STORIES_TO_ANALYZE} stories for analysis...")
    retrieval_agent = RetrievalAgent()
    
    # Call async method and get result dict
    result = await retrieval_agent.select_top_stories(
        news_articles=articles, 
        max_stories=config.MAX_STORIES_TO_ANALYZE
    )
    
    # Extract articles and reasoning from result
    selected_articles = result.get("articles", [])
    reasoning = result.get("reasoning", "")
    
    if reasoning:
        print(f"\nRetrieval Agent Reasoning: {reasoning}")
    
    if not selected_articles:
        print("No articles selected. Exiting.")
        return
    
    print(f"Selected {len(selected_articles)} articles for analysis")
    
    # Step 3: Analyze selected stories
    # Match returned articles back to original articles to preserve link and published fields
    print(f"\nStep 3: Analyzing {len(selected_articles)} selected stories...")
    analysis_agent = AnalysisAgent()
    
    # Create a mapping of title to original article for matching
    original_articles_map = {art.get('title', ''): art for art in articles}
    
    # Ensure articles have all required fields for analysis agent
    formatted_articles = []
    for article in selected_articles:
        title = article.get('title', '')
        # Try to find matching original article by title
        original_article = original_articles_map.get(title)
        
        if original_article:
            # Use original article data, but update with any changes from retrieval agent
            formatted_article = {
                'title': article.get('title', original_article.get('title', '')),
                'source': article.get('source', original_article.get('source', 'Unknown')),
                'summary': article.get('summary', original_article.get('summary', '')),
                'published': original_article.get('published', 'Unknown'),
                'link': original_article.get('link', '')
            }
        else:
            # Fallback if no match found
            formatted_article = {
                'title': article.get('title', ''),
                'source': article.get('source', 'Unknown'),
                'summary': article.get('summary', ''),
                'published': article.get('published', 'Unknown'),
                'link': article.get('link', '')
            }
        formatted_articles.append(formatted_article)
    
    analyses = analysis_agent.analyze_stories(formatted_articles)
    
    # Step 4: Display results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    formatted_output = format_recommendations(analyses)
    print(formatted_output)
    
    # Step 5: Save results
    save_results(analyses)
    
    print("\n" + "=" * 80)
    print("Analysis complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
