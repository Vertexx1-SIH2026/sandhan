export default function VerifyNodeModal({ link, onConfirm, onCancel, submitting, labelFor }) {
  if (!link) return null;
  const label = labelFor || ((x) => x);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-[#1D3157] bg-[#0E1B33] p-6">
        <h3 className="text-base font-semibold text-[#E7ECF3]">Verify predicted link</h3>
        <p className="mt-2 text-sm text-[#9AA7BD]">
          The model has inferred a connection that no record confirms yet. Verifying records that you, the
          investigator, have reviewed the underlying evidence and confirm this link belongs in the case network
          and in any evidence export. This action is written to the case audit log.
        </p>

        <div className="mt-4 rounded-md bg-[#0B1F3A] p-3 mono text-xs text-[#E7ECF3]">
          <div>Source: {label(link.source)}</div>
          <div>Target: {label(link.target)}</div>
          <div className="mt-1 text-[#9AA7BD]">
            Shared neighbours: {link.shared_neighbors}
            {link.via?.length ? ` (${link.via.slice(0, 3).map(label).join(", ")})` : ""} &middot; Score: {link.score}
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded px-3 py-2 text-sm text-[#9AA7BD] hover:text-[#E7ECF3]" disabled={submitting}>
            Cancel
          </button>
          <button onClick={onConfirm} disabled={submitting}
            className="rounded bg-verified px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90 disabled:opacity-50">
            {submitting ? "Verifying..." : "Confirm & verify"}
          </button>
        </div>
      </div>
    </div>
  );
}
