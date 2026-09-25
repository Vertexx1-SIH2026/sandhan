import { useState } from "react";
import { exportEvidencePdf } from "@/services/api";

export default function EvidenceExportButton({ caseId, pendingCount = 0 }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const disabled = pendingCount > 0;

  async function handleExport() {
    setError(null);
    setBusy(true);
    try {
      const blob = await exportEvidencePdf(caseId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `evidence_${caseId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err?.response?.status === 409
        ? "Resolve pending verifications before exporting."
        : "Export failed. Check the backend logs.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="group relative">
      <button onClick={handleExport} disabled={disabled || busy}
        className="rounded bg-verified px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        title={disabled ? "Verify or dismiss every predicted link first" : ""}>
        {busy ? "Generating..." : "Export certificate"}
      </button>
      {disabled && (
        <div className="absolute right-0 top-full z-10 mt-1 hidden w-64 rounded bg-[#0B1F3A] p-2 text-xs text-[#E7ECF3] shadow-lg group-hover:block">
          {pendingCount} predicted link(s) still pending &mdash; verify or dismiss each one before exporting.
        </div>
      )}
      {error && <div className="absolute right-0 top-full z-10 mt-1 w-64 text-xs text-alertred">{error}</div>}
    </div>
  );
}
