import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

export default function Dashboard() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = () => apiGet("/dashboard").then(setData).catch((e) => setErr(String(e)));

  useEffect(() => { load(); }, []);

  const runDaily = () => apiPost("/runs/daily").then(load).catch((e) => setErr(String(e)));
  const runWeekly = () => apiPost("/runs/weekly").then(load).catch((e) => setErr(String(e)));

  if (err) return <div className="card">Error: {err}</div>;
  if (!data) return <div className="card">Loading…</div>;

  return (
    <>
      <h1>Portfolio</h1>
      <div className="card">
        <p><strong>NAV:</strong> ${data.nav?.nav_usd?.toFixed(2)}</p>
        <p><strong>Cash:</strong> ${data.nav?.cash_usd?.toFixed(2)} ({data.nav?.cash_pct}%)</p>
        <p><strong>Pending decisions:</strong> {data.pending_decisions}</p>
        <p><strong>Last analysis:</strong> {data.last_analysis_run_at || "None"}</p>
        <button type="button" onClick={runDaily}>Run daily analysis</button>
        <button type="button" className="secondary" onClick={runWeekly}>Generate weekly plan</button>
      </div>
    </>
  );
}
