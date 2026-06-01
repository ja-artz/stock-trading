import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

export default function Insights() {
  const [report, setReport] = useState<any>(null);

  const load = () => apiGet("/insights/latest").then((r) => setReport(r.report));
  useEffect(() => { load(); }, []);

  const generate = () => apiPost("/insights/generate").then(setReport);

  return (
    <>
      <h1>Insights</h1>
      <button type="button" onClick={generate}>Generate insights report</button>
      {report && (
        <div className="card">
          <p>{report.payload?.summary || report.summary}</p>
          <ul>
            {(report.payload?.what_worked || report.what_worked || []).map((x: string, i: number) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
