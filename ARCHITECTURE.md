# Stock Trading Project Architecture

This diagram reflects the current implementation state of the project.

```mermaid
flowchart TD
    U["User CLI Run"] --> M["main.py Orchestrator"]

    M --> C["config.py Env and runtime settings"]
    C --> E[".env and OS Environment Variables"]

    M --> NC["NewsCollector news_collector.py"]
    NC --> GN["Google News RSS"]
    NC --> WS["Article Web Pages requests and BeautifulSoup summary fallback"]
    NC --> A1["Raw Articles title source summary published link"]

    M --> RAH["RetrievalAgent headline mode"]
    M --> RAU["RetrievalAgent upside mode"]
    RAH --> OA["OpenAI Agents SDK Agent and Runner"]
    RAU --> OA
    OA --> OM["OpenAI Model default gpt-4o-mini"]
    RAH --> FT["function_tool fetch_news_from_rss"]
    RAU --> FT
    FT --> NC
    A1 --> RAH
    A1 --> RAU
    RAH --> H1["Headline Candidates 3 to 5"]
    RAU --> U1["Upside Candidates 3 to 5"]

    M --> MA["Merge and Deduplicate candidates"]
    H1 --> MA
    U1 --> MA
    MA --> A2["Merged Candidate Pool"]

    M --> AA["AnalysisAgent analysis_agent.py"]
    AA --> AC["Anthropic SDK"]
    AC --> AM["Claude Model config ANTHROPIC_MODEL"]
    A2 --> AA
    AA --> T1["Actionability Triage top N"]
    T1 --> A3["Formatted Articles"]
    A3 --> AA
    AA --> SC["Shared context one call"]
    SC --> P1["Persona aggressive"]
    SC --> P2["Persona moderate"]
    SC --> P3["Persona minimal risk"]
    P1 --> R1["Per story multi profile JSON"]
    P2 --> R1
    P3 --> R1

    M --> FR["format_recommendations"]
    R1 --> FR
    FR --> O1["Console Output"]

    M --> SR["save_results"]
    R1 --> SR
    SR --> J["recommendations timestamp json"]
```

## Component Notes

- `main.py` is the orchestration layer and execution entrypoint (`asyncio.run(main())`).
- `config.py` centralizes model IDs, API keys, and operational limits (stories count, news age, RSS source).
- `news_collector.py` handles ingestion/parsing/filtering of Google News RSS entries and optional content fallback scraping.
- `retrieval_agent.py` now runs in two modes: `headline` (major market movers) and `upside` (non-front-page asymmetric opportunities), each returning 3-5 stories.
- `analysis_agent.py` triages merged candidates for actionability, then for each selected story: one shared factual `shared_context` call, then three persona briefs (`aggressive`, `moderate`, `minimal_risk`) with separate recommendations and `portfolio_actions`.
- Results are both human-readable (console) and machine-readable (`recommendations_*.json`).

## Runtime Sequence (Current)

1. Fetch recent general news (`NewsCollector.get_general_news`).
2. Run dual retrieval (`RetrievalAgent.select_top_stories` in `headline` and `upside` modes).
3. Merge and deduplicate candidate pools in `main.py`.
4. Triage candidates for actionability (`AnalysisAgent.select_actionable_stories`).
5. Analyze selected stories in depth (`AnalysisAgent.analyze_stories` -> `analyze_story_multi_profile`: shared context + three personas).
6. Print formatted recommendations.
7. Save JSON output file with timestamp.
