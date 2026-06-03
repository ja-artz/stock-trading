import { useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { DollarSign } from "lucide-react";

export function ImportPositionsDialog({
  portfolioId,
  initialCash = 1000,
  onSaved,
}: {
  portfolioId: number;
  initialCash?: number;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!csvText.trim()) {
      setErr("Choose or paste a CSV file first.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      await api.post("/portfolio/import-csv", {
        portfolio_id: portfolioId,
        cash_usd: initialCash,
        csv_text: csvText,
      });
      setOpen(false);
      setCsvText("");
      onSaved();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = (file: File | null) => {
    if (!file) return;
    file.text().then(setCsvText).catch((e) => setErr(String(e)));
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <DollarSign className="w-4 h-4 mr-2" />
          Import Positions
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import Positions from CSV</DialogTitle>
          <DialogDescription>Upload a CSV file with your current holdings.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div
            className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              onFile(e.dataTransfer.files[0] ?? null);
            }}
          >
            <p className="text-sm text-gray-600 mb-2">Drag and drop CSV file, or click to browse</p>
            <Button variant="outline" size="sm" type="button" asChild>
              <label className="cursor-pointer">
                Choose File
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => onFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </Button>
          </div>
          {csvText && (
            <p className="text-xs text-gray-500">Loaded {csvText.split("\n").filter(Boolean).length - 1} row(s).</p>
          )}
          <p className="text-xs text-gray-500">Expected format: ticker, quantity, avg_cost, instrument_type</p>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={submit} disabled={busy}>
              {busy ? "Importing…" : "Import"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
