import { useEffect, useState } from "react";
import { apiGet, apiPatch } from "../api";

export default function WeeklyPlan() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = () => apiGet("/plans/current").then(setData).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const decide = (id: number, decision: string) =>
    apiPatch(`/plans/items/${id}/decision`, { member_id: 1, decision }).then(load);

  if (err) return <div className="card">Error: {err}</div>;
  if (!data?.plan) return <div className="card">No weekly plan yet. Generate one from Home.</div>;

  const bannerClass = data.is_stale ? "banner stale" : "banner";

  return (
    <>
      <h1>Weekly plan</h1>
      <div className={bannerClass}>{data.staleness_banner}</div>
      <div className="card">
        <p>{data.plan.summary || data.plan.payload?.summary}</p>
        <table>
          <thead>
            <tr>
              <th>#</th><th>Action</th><th>Ticker</th><th>Horizon</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {(data.plan.items || []).map((item: any) => (
              <tr key={item.id}>
                <td>{item.priority}</td>
                <td>{item.action}</td>
                <td>{item.ticker}</td>
                <td>{item.horizon}</td>
                <td>{item.status}</td>
                <td>
                  <button type="button" onClick={() => decide(item.id, "accepted")}>Accept</button>
                  <button type="button" className="secondary" onClick={() => decide(item.id, "rejected")}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
