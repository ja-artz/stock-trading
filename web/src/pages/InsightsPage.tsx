import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function InsightsPage() {
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<{ report: Record<string, unknown> | null }>("/insights/latest").then((r) => {
      if (r.report?.payload) setReport(r.report.payload as Record<string, unknown>);
      else if (r.report) setReport(r.report as Record<string, unknown>);
    });
  }, []);

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api.post<Record<string, unknown>>("/insights/generate");
      setReport(r);
    } finally {
      setBusy(false);
    }
  };

  const summary = String(report?.summary || "");
  const worked = (report?.what_worked as string[]) || [];
  const failed = (report?.what_failed as string[]) || [];
  const improvements = (report?.process_improvements as string[]) || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Insights</h1>
          <p className="text-gray-600 mt-1">Lessons from your paper book (no SPY benchmark in v1)</p>
        </div>
        <Button onClick={generate} disabled={busy}>
          {busy ? "Generating…" : "Generate insights report"}
        </Button>
      </div>

      {!report ? (
        <Card>
          <CardContent className="py-8 text-center text-gray-600">
            No report yet. Log some trades and decisions, then generate.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Latest report</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            {summary && <p>{summary}</p>}
            {worked.length > 0 && (
              <div>
                <p className="font-medium mb-1">What worked</p>
                <ul className="list-disc list-inside text-gray-600">
                  {worked.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            )}
            {failed.length > 0 && (
              <div>
                <p className="font-medium mb-1">What failed</p>
                <ul className="list-disc list-inside text-gray-600">
                  {failed.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            )}
            {improvements.length > 0 && (
              <div>
                <p className="font-medium mb-1">Process improvements</p>
                <ul className="list-disc list-inside text-gray-600">
                  {improvements.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
