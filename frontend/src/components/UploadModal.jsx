import { useState } from "react";

const FILE_TYPES = [
  { value: "", label: "Auto-detect from columns (recommended)" },
  { value: "fir", label: "FIR (PDF or TXT)" },
  { value: "cdr", label: "CDR (CSV)" },
  { value: "upi", label: "UPI / bank transactions (CSV)" },
  { value: "ipdr", label: "IPDR (CSV)" },
  { value: "records", label: "Generic records (historical-DB format CSV)" },
];

export default function UploadModal({ open, onClose, onUpload, progressLog = [], uploading, caseId }) {
  const [files, setFiles] = useState([]);
  const [declaredType, setDeclaredType] = useState("");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-lg border border-[#1D3157] bg-[#0E1B33] p-6">
        <h3 className="text-base font-semibold text-[#E7ECF3]">Ingest files into {caseId}</h3>
        <p className="mt-1 text-sm text-[#9AA7BD]">
          Select several files at once (e.g. cdr.csv, upi.csv, ipdr.csv and the FIR). Originals are locked
          read-only; after ingestion the case is matched against the whole historical database.
        </p>

        <label className="mt-4 block text-xs text-[#9AA7BD]">File type</label>
        <select value={declaredType} onChange={(e) => setDeclaredType(e.target.value)}
          className="mt-1 w-full rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm text-[#E7ECF3]">
          {FILE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>

        <label className="mt-4 block text-xs text-[#9AA7BD]">Files</label>
        <input type="file" multiple accept=".csv,.pdf,.txt"
          onChange={(e) => setFiles(Array.from(e.target.files))}
          className="mt-1 w-full text-sm text-[#9AA7BD] file:mr-3 file:rounded file:border-0 file:bg-[#1D3157] file:px-3 file:py-2 file:text-[#E7ECF3]" />

        {progressLog.length > 0 && (
          <div className="mt-4 max-h-44 overflow-y-auto rounded bg-[#0B1F3A] p-2 mono text-xs text-[#9AA7BD]">
            {progressLog.map((entry, i) => (
              <div key={i} className={entry.startsWith("FAILED") ? "text-alertred" : ""}>&gt; {entry}</div>
            ))}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded px-3 py-2 text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">Close</button>
          <button onClick={() => onUpload(files, declaredType || null)} disabled={files.length === 0 || uploading}
            className="rounded bg-signal px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90 disabled:opacity-50">
            {uploading ? "Ingesting..." : "Upload & ingest"}
          </button>
        </div>
      </div>
    </div>
  );
}
