import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type StoryEnvelope } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { TickerDisplay } from "@/components/TickerDisplay";
import { ArrowLeft, ExternalLink, Flame, Target, Shield, MessageSquare } from "lucide-react";
import { useChatContext } from "@/context/ChatContext";
import { tierShortLabel } from "@/lib/tierLabels";

const PERSONAS = [
  { id: "aggressive", label: "Aggressive", icon: Flame },
  { id: "moderate", label: "Moderate", icon: Target },
  { id: "minimal_risk", label: "Minimal risk", icon: Shield },
];

export function StoryDetailPage() {
  const { index } = useParams();
  const [story, setStory] = useState<StoryEnvelope | null>(null);
  const [runId, setRunId] = useState<number | undefined>();
  const { openChat } = useChatContext();

  useEffect(() => {
    const i = Number(index);
    api.get<{ stories: StoryEnvelope[]; run_id?: number }>("/stories").then((r) => {
      if (r.run_id) setRunId(r.run_id);
      if (!Number.isNaN(i) && r.stories[i]) setStory(r.stories[i]);
    });
  }, [index]);

  if (!story) {
    return <p className="text-gray-600">Story not found.</p>;
  }

  const sc = story.shared_context as Record<string, unknown> | undefined;
  const ie = story.indirect_effects;
  const profiles = story.analyst_profiles || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/stories">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Stories
          </Button>
        </Link>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            openChat({
              focus: { type: "story", story_index: Number(index), run_id: runId },
            })
          }
        >
          <MessageSquare className="w-4 h-4 mr-2" />
          Discuss with trader agent
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex gap-2 mb-2">
            <Badge>{story.retrieval_type === "headline" ? "Headline" : "Upside"}</Badge>
            {ie?.enabled && (
              <Badge variant="outline" className="border-violet-300 text-violet-800">
                Indirect effects
              </Badge>
            )}
          </div>
          <CardTitle className="text-2xl">{story.article_title}</CardTitle>
          {story.article_link && (
            <a href={story.article_link} target="_blank" rel="noreferrer">
              <Button variant="outline" size="sm" className="mt-4">
                <ExternalLink className="w-4 h-4 mr-2" />
                Read article
              </Button>
            </a>
          )}
        </CardHeader>
      </Card>

      {sc && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Shared context</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>
              <span className="font-medium">Domain:</span> {String(sc.story_domain || "—")} ·{" "}
              <span className="font-medium">Catalyst:</span> {String(sc.catalyst_type)} ·{" "}
              <span className="font-medium">Timeline:</span> {String(sc.timeline)} ·{" "}
              <span className="font-medium">Confidence:</span> {String(sc.confidence)}/10
            </p>
            {(sc.key_drivers as string[] | undefined)?.length ? (
              <ul className="list-disc list-inside text-gray-600">
                {(sc.key_drivers as string[]).map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            ) : null}
            {((sc.affected_companies as { ticker?: string; company_name?: string }[]) || []).length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {(sc.affected_companies as { ticker?: string; company_name?: string }[]).map((c) =>
                  c.ticker ? (
                    <Badge key={c.ticker} variant="outline">
                      <TickerDisplay symbol={c.ticker} companyName={c.company_name} layout="inline" />
                    </Badge>
                  ) : null
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {ie?.enabled && (ie.causal_chains?.length ?? 0) > 0 && (
        <Card className="border-violet-200">
          <CardHeader>
            <CardTitle className="text-base">Indirect effects (2nd / 3rd order)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            {(ie.discarded_obvious?.length ?? 0) > 0 && (
              <div>
                <p className="font-medium text-gray-700 mb-1">Crowded first-order trades (not primary)</p>
                <ul className="list-disc list-inside text-gray-600">
                  {ie.discarded_obvious!.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </div>
            )}
            {ie.causal_chains!.map((chain, ci) => (
              <div key={ci} className="p-3 bg-violet-50/50 rounded-lg space-y-2">
                <p className="font-medium">
                  Chain {ci + 1} (order {chain.order ?? "?"}) — {chain.thesis_one_liner}
                </p>
                {(chain.steps?.length ?? 0) > 0 && (
                  <ol className="list-decimal list-inside text-gray-700 space-y-0.5">
                    {chain.steps!.map((step, si) => (
                      <li key={si}>{step}</li>
                    ))}
                  </ol>
                )}
                {(chain.tickers?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {chain.tickers!.map((t) => (
                      <Badge key={t.ticker} variant="outline">
                        <TickerDisplay symbol={t.ticker} companyName={t.company_name} layout="inline" />
                        <span className="text-gray-600">
                          {" "}
                          · {t.role} · {t.confidence}/10
                        </span>
                      </Badge>
                    ))}
                  </div>
                )}
                <p className="text-xs text-gray-600">
                  Priced-in risk: {chain.already_priced_risk ?? "—"} · Liquidity OK:{" "}
                  {chain.liquidity_ok === false ? "no" : "yes"}
                </p>
                {(chain.falsifiers?.length ?? 0) > 0 && (
                  <p className="text-xs text-gray-600">
                    <span className="font-medium">Falsifiers:</span> {chain.falsifiers!.join("; ")}
                  </p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Analyst views</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="aggressive">
            <TabsList className="grid w-full grid-cols-3">
              {PERSONAS.map((p) => (
                <TabsTrigger key={p.id} value={p.id} className="gap-2">
                  <p.icon className="w-4 h-4" />
                  {p.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {PERSONAS.map((p) => {
              const brief = profiles[p.id] as Record<string, unknown> | undefined;
              return (
                <TabsContent key={p.id} value={p.id} className="mt-6 space-y-4">
                  {brief?.error ? (
                    <p className="text-red-600">{String(brief.error)}</p>
                  ) : (
                    <>
                      <Alert className="border-blue-200 bg-blue-50">
                        <AlertDescription>{String(brief?.thesis || "")}</AlertDescription>
                      </Alert>
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          Risk: {String(brief?.risk_level)}/10 · Suggested tier:{" "}
                          {tierShortLabel(
                            typeof brief?.recommended_tier === "number"
                              ? brief.recommended_tier
                              : Number(brief?.recommended_tier) || null,
                            true
                          )}
                        </div>
                        <div>Return range: {String(brief?.expected_return_range || "—")}</div>
                      </div>
                      {(brief?.recommendations as unknown[])?.length ? (
                        <div>
                          <p className="font-medium mb-2">Recommendations</p>
                          <ul className="space-y-2 text-sm">
                            {(brief?.recommendations as Record<string, string>[]).map((rec, i) => (
                              <li key={i} className="p-2 bg-gray-50 rounded-lg">
                                <TickerDisplay
                                  symbol={rec.ticker}
                                  companyName={rec.company_name as string | undefined}
                                  layout="inline"
                                />
                                <span className="text-gray-600">
                                  {" "}
                                  · {rec.instrument_type} — {rec.rationale}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </>
                  )}
                </TabsContent>
              );
            })}
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
