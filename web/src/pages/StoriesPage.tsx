import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StoryEnvelope } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { RunProgressPanel } from "@/components/RunProgressPanel";
import { useDailyRun } from "@/hooks/useDailyRun";
import { TickerDisplay } from "@/components/TickerDisplay";
import { Clock, ExternalLink, Search, Play } from "lucide-react";

export function StoriesPage() {
  const [stories, setStories] = useState<StoryEnvelope[]>([]);
  const [runAt, setRunAt] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const dailyRun = useDailyRun();

  const load = () =>
    api.get<{ stories: StoryEnvelope[]; run_at: string | null }>("/stories").then((r) => {
      setStories(r.stories || []);
      setRunAt(r.run_at);
    });

  useEffect(() => {
    load().catch(console.error);
  }, []);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return stories;
    return stories.filter((s) => (s.article_title || "").toLowerCase().includes(q));
  }, [stories, search]);

  const byType = (type: string) =>
    filtered.filter((s) => (type === "headline" ? s.retrieval_type === "headline" : s.retrieval_type === "upside"));

  const runDaily = () => dailyRun.run(load);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Stories & Analysis</h1>
          <p className="text-gray-600 mt-1">
            {runAt ? `From run ${new Date(runAt).toLocaleString()}` : "No analysis yet"}
          </p>
        </div>
        <Button variant="outline" onClick={runDaily} disabled={dailyRun.busy}>
          <Play className="w-4 h-4 mr-2" />
          {dailyRun.busy ? "Running…" : "Run daily analysis"}
        </Button>
      </div>

      <RunProgressPanel
        open={dailyRun.busy || dailyRun.logs.length > 0}
        busy={dailyRun.busy}
        stageLabel={dailyRun.stageLabel}
        logs={dailyRun.logs}
        error={dailyRun.error}
        titles={{
          running: "Daily analysis in progress",
          failed: "Analysis failed",
          done: "Analysis complete",
        }}
        hint="This can take several minutes — news fetch, story selection, and three analyst personas per story."
      />

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <Input
          className="pl-10"
          placeholder="Search by title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {!stories.length ? (
        <Card>
          <CardContent className="py-8 text-center text-gray-600">
            No stories yet. Run daily analysis from Home.
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="all">
          <TabsList>
            <TabsTrigger value="all">All ({filtered.length})</TabsTrigger>
            <TabsTrigger value="headline">Headline ({byType("headline").length})</TabsTrigger>
            <TabsTrigger value="upside">Upside ({byType("upside").length})</TabsTrigger>
          </TabsList>
          <TabsContent value="all" className="space-y-4 mt-6">
            {filtered.map((story, i) => (
              <StoryCard key={i} index={i} story={story} />
            ))}
          </TabsContent>
          <TabsContent value="headline" className="space-y-4 mt-6">
            {byType("headline").map((story, i) => (
              <StoryCard key={i} index={stories.indexOf(story)} story={story} />
            ))}
          </TabsContent>
          <TabsContent value="upside" className="space-y-4 mt-6">
            {byType("upside").map((story, i) => (
              <StoryCard key={i} index={stories.indexOf(story)} story={story} />
            ))}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function StoryCard({ story, index }: { story: StoryEnvelope; index: number }) {
  const sc = story.shared_context as Record<string, unknown> | undefined;
  const type = story.retrieval_type === "headline" ? "headline" : "upside";
  const companies =
    (sc?.affected_companies as { ticker?: string; company_name?: string }[] | undefined)?.filter(
      (c) => c.ticker
    ) || [];
  const hasIndirect = Boolean(story.indirect_effects?.enabled);

  return (
    <Link to={`/stories/${index}`}>
      <Card className="hover:border-blue-300 transition-colors">
        <CardHeader>
          <div className="flex justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <Badge variant={type === "headline" ? "default" : "secondary"}>
                  {type === "headline" ? "Headline" : "Upside"}
                </Badge>
                {hasIndirect && (
                  <Badge variant="outline" className="border-violet-300 text-violet-800">
                    Indirect
                  </Badge>
                )}
                <span className="text-sm text-gray-500">{story.article_published || ""}</span>
              </div>
              <CardTitle className="text-lg">{story.article_title}</CardTitle>
            </div>
            <ExternalLink className="w-4 h-4 text-gray-400 shrink-0" />
          </div>
        </CardHeader>
        <CardContent>
          {sc && (
            <div className="flex flex-wrap gap-4 text-sm text-gray-600">
              <span>Catalyst: {String(sc.catalyst_type || "—")}</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" /> {String(sc.timeline || "—")}
              </span>
            </div>
          )}
          {companies.length > 0 && (
            <div className="mt-2 flex gap-2 flex-wrap">
              {companies.slice(0, 6).map((c) => (
                <Badge key={c.ticker} variant="outline">
                  <TickerDisplay symbol={c.ticker} companyName={c.company_name} layout="inline" />
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
