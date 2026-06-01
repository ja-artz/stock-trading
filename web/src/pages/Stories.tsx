import { useEffect, useState } from "react";
import { apiGet } from "../api";

export default function Stories() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    apiGet("/stories").then(setData);
  }, []);

  if (!data) return <div className="card">Loading…</div>;
  if (!data.stories?.length) return <div className="card">No stories. Run daily analysis first.</div>;

  return (
    <>
      <h1>Stories</h1>
      {data.stories.map((s: any, i: number) => (
        <div className="card" key={i}>
          <h3>{s.article_title}</h3>
          <p><em>{s.retrieval_type}</em> · {s.article_published}</p>
          {s.article_link && <p><a href={s.article_link} target="_blank" rel="noreferrer">Article</a></p>}
          {Object.entries(s.analyst_profiles || {}).map(([pid, brief]: [string, any]) => (
            <details key={pid}>
              <summary>{pid.replace("_", " ")}</summary>
              <p>{brief.thesis || brief.error}</p>
            </details>
          ))}
        </div>
      ))}
    </>
  );
}
