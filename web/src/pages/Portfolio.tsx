import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

export default function Portfolio() {
  const [data, setData] = useState<any>(null);
  const [form, setForm] = useState({
    side: "buy", ticker: "", quantity: "1", price: "", instrument_type: "stock",
  });

  const load = () => apiGet("/portfolio").then(setData);
  useEffect(() => { load(); }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    apiPost("/trades", {
      portfolio_id: 1,
      side: form.side,
      ticker: form.ticker.toUpperCase(),
      instrument_type: form.instrument_type,
      quantity: parseFloat(form.quantity),
      price: parseFloat(form.price),
    }).then(load);
  };

  if (!data) return <div className="card">Loading…</div>;

  return (
    <>
      <h1>Portfolio</h1>
      <div className="card">
        <p>Cash: ${data.state?.cash_usd?.toFixed(2)} · NAV: ${data.state?.nav_usd?.toFixed(2)}</p>
        <table>
          <thead><tr><th>Ticker</th><th>Type</th><th>Qty</th><th>Value</th></tr></thead>
          <tbody>
            {(data.state?.positions || []).map((p: any) => (
              <tr key={`${p.ticker}-${p.instrument_type}`}>
                <td>{p.ticker}</td><td>{p.instrument_type}</td><td>{p.quantity}</td>
                <td>${p.market_value?.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Log trade (Sofi)</h3>
        <form onSubmit={submit}>
          <p>
            <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}>
              <option value="buy">Buy</option><option value="sell">Sell</option>
            </select>
            <input placeholder="Ticker" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value })} required />
            <input placeholder="Qty" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
            <input placeholder="Price" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} required />
            <select value={form.instrument_type} onChange={(e) => setForm({ ...form, instrument_type: e.target.value })}>
              <option value="stock">Stock</option>
              <option value="call_option">Call</option>
              <option value="put_option">Put</option>
            </select>
          </p>
          <button type="submit">Log trade</button>
        </form>
      </div>
    </>
  );
}
