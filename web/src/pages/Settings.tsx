import { useEffect, useState } from "react";
import { apiGet } from "../api";

export default function Settings() {
  const [rules, setRules] = useState<any>(null);
  const [apiKey, setApiKey] = useState(localStorage.getItem("apiKey") || "");

  useEffect(() => {
    apiGet("/settings/rules").then(setRules);
  }, []);

  const saveKey = () => {
    localStorage.setItem("apiKey", apiKey);
    alert("API key saved locally");
  };

  return (
    <>
      <h1>Settings</h1>
      <div className="card">
        <h3>API key</h3>
        <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} style={{ width: "100%" }} />
        <button type="button" onClick={saveKey}>Save</button>
      </div>
      {rules && (
        <div className="card">
          <h3>Trading rules</h3>
          <pre>{JSON.stringify(rules.rules, null, 2)}</pre>
          {rules.session?.started_at && (
            <p className="disclaimer">Session started {rules.session.started_at}</p>
          )}
        </div>
      )}
    </>
  );
}
