import React, { useCallback, useEffect, useState } from "react";
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
import { Check, X, Clock, Play, AlertCircle } from "lucide-react";

export function RecommendationsPage() {
  const [data, setData] = useState<TradingPlanResponse | null>(null);
  const planRun = useTradingPlanRun();

  const load = useCallback(() => {
    api.get<TradingPlanResponse>("/plans/current").then(setData);
  }, []);

  useEffect(() => {
    load();
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

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Trading plan</h1>
          <p className="text-gray-600 mt-1">
            On-demand recommendations from the trader agent — not tied to a weekly calendar
          </p>
        </div>
        <div className="flex gap-2">
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
        <>
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

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{items.length}</div>
                <p className="text-sm text-gray-600">{noChanges ? "Action items" : "Total items"}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold text-amber-600">{pending}</div>
                <p className="text-sm text-gray-600">Pending review</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{plan.summary || plan.payload?.summary || "Plan"}</CardTitle>
            </CardHeader>
            <CardContent>
              {items.length === 0 ? (
                <p className="text-gray-600 text-sm mb-4">
                  {noChanges
                    ? "The trader agent evaluated current conditions and did not suggest new trades."
                    : "This plan has no line items."}
                </p>
              ) : null}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Thesis</TableHead>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Horizon</TableHead>
                    <TableHead>Suggested size</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <PlanRow key={item.id} item={item} onDecided={load} />
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function PlanItemSizing({ item }: { item: PlanItem }) {
  const primary = item.sizing_summary?.trim();
  if (primary) {
    return (
      <div>
        <div className="font-medium">{primary}</div>
        {item.size_hint && (
          <div className="text-xs text-gray-500 mt-0.5">Tag: {item.size_hint}</div>
        )}
      </div>
    );
  }
  if (item.size_hint) {
    return <span className="text-gray-600">{item.size_hint}</span>;
  }
  return <span className="text-gray-400">—</span>;
}

function PlanRow({ item, onDecided }: { item: PlanItem; onDecided: () => void }) {
  const consensus = item.persona_consensus;
  const agree = consensus ? Object.values(consensus).filter(Boolean).length : 0;

  return (
    <TableRow>
      <TableCell>{item.priority}</TableCell>
      <TableCell>
        <Badge>{item.action}</Badge>
      </TableCell>
      <TableCell>
        {(item.thesis_type || item.detail?.thesis_type) === "indirect" ? (
          <Badge variant="outline" className="border-violet-300 text-violet-800">
            Indirect
          </Badge>
        ) : (
          <span className="text-xs text-gray-500">First-order</span>
        )}
      </TableCell>
      <TableCell>
        <TickerDisplay symbol={item.ticker} companyName={item.company_name} />
      </TableCell>
      <TableCell>{item.horizon || "—"}</TableCell>
      <TableCell>
        <PlanItemSizing item={item} />
        {item.rule_warnings && item.rule_warnings.length > 0 && (
          <ul className="mt-1 text-xs text-amber-700 list-disc pl-4 space-y-0.5">
            {item.rule_warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </TableCell>
      <TableCell>
        <PlanStatusBadges item={item} />
        {agree > 0 && <span className="ml-2 text-xs text-gray-500">{agree}/3 personas</span>}
      </TableCell>
      <TableCell>
        <div className="flex gap-1 flex-wrap justify-end">
          {item.status === "pending" && (
            <>
              <DecisionButton itemId={item.id} decision="accepted" icon={<Check className="w-4 h-4 text-green-600" />} onDone={onDecided} />
              <DecisionButton itemId={item.id} decision="rejected" icon={<X className="w-4 h-4 text-red-600" />} onDone={onDecided} />
              <DecisionButton itemId={item.id} decision="deferred" icon={<Clock className="w-4 h-4 text-amber-600" />} onDone={onDecided} />
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function PlanStatusBadges({ item }: { item: PlanItem }) {
  const status = item.status;
  if (status === "accepted") {
    const exec = item.execution_status;
    return (
      <div className="flex flex-col gap-1 items-start">
        <Badge variant="outline" className="border-green-300 text-green-800">
          Accepted
        </Badge>
        {exec === "executed" ? (
          <Badge variant="secondary" className="text-xs">
            Executed in portfolio
          </Badge>
        ) : exec === "pending" ? (
          <Badge variant="outline" className="text-xs border-amber-300 text-amber-800">
            Pending execution
          </Badge>
        ) : null}
      </div>
    );
  }
  return (
    <Badge variant="outline" className="capitalize">
      {status}
    </Badge>
  );
}

function DecisionButton({
  itemId,
  decision,
  icon,
  onDone,
}: {
  itemId: number;
  decision: string;
  icon: React.ReactNode;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);

  const [error, setError] = useState("");

  const save = async () => {
    setError("");
    try {
      await api.patch(`/plans/items/${itemId}/decision`, {
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
        <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
          {icon}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="capitalize">{decision}</DialogTitle>
          <DialogDescription>
            {decision === "accepted"
              ? "Marks this line as accepted for your household. Log the actual trade in Portfolio when you execute in Sofi — status will show Executed once the book reflects it."
              : "Optional note for your household record."}
          </DialogDescription>
        </DialogHeader>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Why?" />
        {error && <p className="text-sm text-red-600">{error}</p>}
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
