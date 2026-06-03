import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type PlanItem, type TradingPlanResponse } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { RunProgressPanel } from "@/components/RunProgressPanel";
import { useTradingPlanRun } from "@/hooks/useTradingPlanRun";
import { TickerDisplay } from "@/components/TickerDisplay";
import { TierBadge } from "@/components/TierBadge";
import { getTierDefinition } from "@/lib/tierLabels";
import {
  Check,
  X,
  Clock,
  Play,
  AlertCircle,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  Calendar,
} from "lucide-react";
import { useChatContext } from "@/context/ChatContext";

function actionBadgeVariant(action: string): "default" | "destructive" | "secondary" | "outline" {
  const a = action.toLowerCase();
  if (a === "buy") return "default";
  if (a === "sell" || a === "trim") return "destructive";
  if (a === "hedge") return "secondary";
  return "outline";
}

function formatInstrument(type: string | null | undefined): string {
  if (!type) return "Stock";
  const t = type.toLowerCase();
  if (t.includes("call")) return "Call option";
  if (t.includes("put")) return "Put option";
  return "Stock";
}

function PersonaConsensus({ item }: { item: PlanItem }) {
  const consensus = item.persona_consensus;
  const agree = consensus ? Object.values(consensus).filter(Boolean).length : 0;
  return (
    <div className="flex gap-1">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
            i < agree ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-400"
          }`}
        >
          {i < agree ? "✓" : "−"}
        </div>
      ))}
    </div>
  );
}

export function RecommendationsPage() {
  const [data, setData] = useState<TradingPlanResponse | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const planRun = useTradingPlanRun();
  const { openChat } = useChatContext();

  const load = useCallback(() => {
    api.get<TradingPlanResponse>("/plans/current").then(setData);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onUpdated = () => load();
    window.addEventListener("trading-plan-updated", onUpdated);
    return () => window.removeEventListener("trading-plan-updated", onUpdated);
  }, [load]);

  const generate = () => planRun.run(load);

  const clearRecommendations = async () => {
    if (
      !confirm(
        "Clear all trading plans and decisions? Your Portfolio trades and positions are kept. You can generate a new plan after."
      )
    )
      return;
    await api.post("/plans/clear", { portfolio_id: 1 });
    load();
  };

  const plan = data?.plan;
  const items = plan?.items || [];
  const noChanges = Boolean(data?.no_changes ?? plan?.no_changes ?? plan?.payload?.no_changes);
  const pending = items.filter((i) => i.status === "pending").length;
  const accepted = items.filter((i) => i.status === "accepted").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Trading plan</h1>
          <p className="text-gray-600 mt-1">
            On-demand recommendations from the trader agent. Use the chat button to discuss any line item.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {plan && (
            <Button
              variant="outline"
              onClick={() => openChat({ focus: { type: "trading_plan" }, weeklyPlanId: plan.id })}
            >
              <MessageSquare className="w-4 h-4 mr-2" />
              Discuss plan
            </Button>
          )}
          {plan && (
            <Button
              variant="outline"
              onClick={clearRecommendations}
              disabled={planRun.busy}
              className="text-amber-800 border-amber-300"
            >
              Clear recommendations
            </Button>
          )}
          <Button variant="outline" onClick={generate} disabled={planRun.busy}>
            <Play className="w-4 h-4 mr-2" />
            {planRun.busy ? "Generating…" : "Generate trading plan"}
          </Button>
        </div>
      </div>

      <RunProgressPanel
        open={planRun.busy || planRun.logs.length > 0}
        busy={planRun.busy}
        stageLabel={planRun.stageLabel}
        logs={planRun.logs}
        error={planRun.error}
        titles={{
          running: "Trading plan in progress",
          failed: "Plan generation failed",
          done: "Trading plan complete",
        }}
        hint="Uses latest analysis, how long ago the last plan was generated, and your current holdings. May recommend no changes if conditions are unchanged."
      />

      {!plan ? (
        <Card>
          <CardContent className="py-8 text-center text-gray-600">
            No trading plan yet. Run daily analysis first, then generate a trading plan.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          <Alert className={data?.is_stale ? "border-amber-200 bg-amber-50" : "border-blue-200 bg-blue-50"}>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {data?.plan_ago_label || plan.plan_ago_label
                ? `Plan generated ${data?.plan_ago_label || plan.plan_ago_label}. `
                : ""}
              {data?.staleness_banner || `Based on analysis from ${plan.based_on_analysis_at}`}
            </AlertDescription>
          </Alert>

          {noChanges && (
            <Alert className="border-green-200 bg-green-50">
              <AlertCircle className="h-4 w-4 text-green-700" />
              <AlertDescription className="text-green-900">
                No new trades recommended — analysis unchanged since the last plan. Open recommendations below
                are unchanged; accept, defer, or reject as you execute in Sofi.
              </AlertDescription>
            </Alert>
          )}

          <Card className="bg-blue-50 border-blue-200">
            <CardContent className="pt-6">
              <p className="text-sm text-gray-700">
                {plan.summary ||
                  plan.payload?.summary ||
                  "This plan combines the latest news analysis with your current cash and positions. Mark each line after you discuss; log trades in Sofi separately."}
              </p>
            </CardContent>
          </Card>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{items.length}</div>
                <p className="text-sm text-gray-600">{noChanges ? "Open items" : "Total items"}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold text-amber-600">{pending}</div>
                <p className="text-sm text-gray-600">Pending review</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold text-green-600">{accepted}</div>
                <p className="text-sm text-gray-600">Accepted</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">
                  {items.filter((i) => i.execution_status === "executed").length}
                </div>
                <p className="text-sm text-gray-600">Executed in portfolio</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Recommendations ({items.length})</CardTitle>
            </CardHeader>
            <CardContent>
              {items.length === 0 ? (
                <p className="text-gray-600 text-sm mb-4">
                  {noChanges
                    ? "The trader agent evaluated current conditions and did not suggest new trades."
                    : "This plan has no line items."}
                </p>
              ) : (
                <div className="border rounded-lg overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12" />
                        <TableHead className="w-16">#</TableHead>
                        <TableHead>Action</TableHead>
                        <TableHead>Ticker / Instrument</TableHead>
                        <TableHead title="Capital tier (T1–T3) and thesis horizon">Tier / horizon</TableHead>
                        <TableHead>Size</TableHead>
                        <TableHead>Consensus</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="w-36">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((item) => (
                        <PlanRowGroup
                          key={item.id}
                          item={item}
                          expanded={expandedRow === item.id}
                          onToggle={() => setExpandedRow(expandedRow === item.id ? null : item.id)}
                          onDecided={load}
                          onDiscuss={() =>
                            openChat({
                              focus: {
                                type: "plan_item",
                                plan_item_id: item.id,
                                ticker: item.ticker,
                                action: item.action,
                                rationale: item.rationale,
                              },
                              weeklyPlanId: plan.id,
                            })
                          }
                        />
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <p className="text-sm text-gray-600">
              Review all recommendations and record your decisions. Log actual trades in Portfolio.
            </p>
            <Link to="/portfolio">
              <Button>
                <Calendar className="w-4 h-4 mr-2" />
                Log trade in Sofi
              </Button>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function PlanRowGroup({
  item,
  expanded,
  onToggle,
  onDecided,
  onDiscuss,
}: {
  item: PlanItem;
  expanded: boolean;
  onToggle: () => void;
  onDecided: () => void;
  onDiscuss: () => void;
}) {
  const sizing = item.sizing_summary?.trim();
  const isIndirect = (item.thesis_type || item.detail?.thesis_type) === "indirect";

  return (
    <>
      <TableRow className="cursor-pointer hover:bg-gray-50">
        <TableCell onClick={onToggle}>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-500" />
          )}
        </TableCell>
        <TableCell className="font-medium" onClick={onToggle}>
          {item.priority}
        </TableCell>
        <TableCell onClick={onToggle}>
          <Badge variant={actionBadgeVariant(item.action)} className="capitalize">
            {item.action}
          </Badge>
        </TableCell>
        <TableCell onClick={onToggle}>
          <div>
            <TickerDisplay symbol={item.ticker} companyName={item.company_name} className="font-mono font-medium" />
            <div className="text-sm text-gray-500">{formatInstrument(item.instrument_type)}</div>
          </div>
        </TableCell>
        <TableCell onClick={onToggle}>
          <div className="flex flex-wrap gap-1">
            {item.capital_tier != null && (
              <TierBadge tier={item.capital_tier} showId />
            )}
            {item.horizon ? (
              <Badge variant="outline" className="capitalize">
                {item.horizon}
              </Badge>
            ) : (
              !item.capital_tier && "—"
            )}
          </div>
        </TableCell>
        <TableCell onClick={onToggle}>
          <div>
            <div className="font-medium text-sm line-clamp-2 max-w-[220px]">{sizing || item.size_hint || "—"}</div>
            {item.pct_nav != null && (
              <div className="text-xs text-gray-500">{item.pct_nav.toFixed(0)}% of NAV</div>
            )}
          </div>
        </TableCell>
        <TableCell onClick={onToggle}>
          <PersonaConsensus item={item} />
        </TableCell>
        <TableCell onClick={onToggle}>
          <PlanStatusBadges item={item} />
        </TableCell>
        <TableCell>
          <div className="flex gap-1 justify-end items-center">
            <Button
              size="sm"
              variant="ghost"
              className="h-8 px-2 text-blue-700"
              title="Discuss with trader agent"
              onClick={(e) => {
                e.stopPropagation();
                onDiscuss();
              }}
            >
              <MessageSquare className="w-4 h-4" />
            </Button>
            {item.status === "pending" && (
              <>
                <DecisionButton
                  item={item}
                  decision="accepted"
                  icon={<Check className="w-4 h-4 text-green-600" />}
                  onDone={onDecided}
                />
                <DecisionButton
                  item={item}
                  decision="rejected"
                  icon={<X className="w-4 h-4 text-red-600" />}
                  onDone={onDecided}
                />
                <DecisionButton
                  item={item}
                  decision="deferred"
                  icon={<Clock className="w-4 h-4 text-amber-600" />}
                  onDone={onDecided}
                />
              </>
            )}
          </div>
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={9} className="bg-gray-50">
            <div className="py-4 px-6 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm p-3 bg-blue-50 rounded-lg">
                <div>
                  <p className="text-gray-600">Thesis</p>
                  <p className="font-medium">{isIndirect ? "Indirect" : "First-order"}</p>
                </div>
                <div>
                  <p className="text-gray-600">Capital tier</p>
                  {item.capital_tier != null ? (
                    <div className="mt-0.5 space-y-1">
                      <TierBadge tier={item.capital_tier} showId />
                      <p className="text-xs text-gray-600">
                        {getTierDefinition(item.capital_tier)?.hint}
                      </p>
                    </div>
                  ) : (
                    <p className="font-medium">—</p>
                  )}
                </div>
                <div>
                  <p className="text-gray-600">Suggested size</p>
                  <p className="font-medium">{sizing || item.size_hint || "—"}</p>
                </div>
                <div>
                  <p className="text-gray-600">Horizon</p>
                  <p className="font-medium capitalize">{item.horizon || "—"}</p>
                </div>
              </div>
              {item.rationale && (
                <div>
                  <p className="text-sm font-medium">Full rationale</p>
                  <p className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">{item.rationale}</p>
                </div>
              )}
              {item.rule_warnings && item.rule_warnings.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-amber-800">Rule warnings</p>
                  <ul className="mt-1 text-sm text-amber-800 list-disc pl-4 space-y-1">
                    {item.rule_warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              {item.latest_decision?.note && (
                <div>
                  <p className="text-sm font-medium">Decision notes</p>
                  <p className="text-sm text-gray-600 mt-1">{item.latest_decision.note}</p>
                </div>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={onDiscuss}
              >
                <MessageSquare className="w-4 h-4 mr-2" />
                Discuss this line with trader agent
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function PlanStatusBadges({ item }: { item: PlanItem }) {
  const status = item.status;
  if (status === "accepted") {
    const exec = item.execution_status;
    return (
      <div className="flex flex-col gap-1 items-start">
        <Badge variant="default">Accepted</Badge>
        {exec === "executed" ? (
          <Badge variant="secondary" className="text-xs">
            Executed
          </Badge>
        ) : exec === "pending" ? (
          <Badge variant="outline" className="text-xs border-amber-300 text-amber-800">
            Pending execution
          </Badge>
        ) : null}
      </div>
    );
  }
  if (status === "rejected") {
    return <Badge variant="destructive">Rejected</Badge>;
  }
  if (status === "deferred") {
    return <Badge variant="secondary">Deferred</Badge>;
  }
  if (status === "superseded") {
    return <Badge variant="outline">Superseded</Badge>;
  }
  return <Badge variant="outline">Pending</Badge>;
}

function DecisionButton({
  item,
  decision,
  icon,
  onDone,
}: {
  item: PlanItem;
  decision: string;
  icon: React.ReactNode;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const titles: Record<string, string> = {
    accepted: "Accept recommendation",
    rejected: "Reject recommendation",
    deferred: "Defer decision",
  };

  const save = async () => {
    setError("");
    try {
      await api.patch(`/plans/items/${item.id}/decision`, {
        member_id: 1,
        decision,
        note: note || undefined,
      });
      setOpen(false);
      setNote("");
      onDone();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className="h-8 w-8 p-0"
          onClick={(e) => e.stopPropagation()}
        >
          {icon}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="capitalize">{titles[decision] || decision}</DialogTitle>
          <DialogDescription>
            {decision === "accepted"
              ? "Marks this line as accepted. Log the actual trade in Portfolio when you execute in Sofi."
              : "Optional note for your household record."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="bg-gray-50 p-4 rounded-lg">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <Badge variant={actionBadgeVariant(item.action)} className="capitalize">
                {item.action}
              </Badge>
              <TickerDisplay symbol={item.ticker} companyName={item.company_name} />
            </div>
            <p className="text-sm text-gray-600 line-clamp-3">{item.rationale}</p>
          </div>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Why?" />
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={save}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
