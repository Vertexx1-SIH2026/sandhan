import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { baselineSearch, getSession } from "@/services/api";

/**
 * Act 1 of the demo -- "how it works today": a plain keyword/SQL lookup over
 * fragmented record tables. It returns isolated rows with no linkage, no
 * roles, no network. Compare with the case network view.
 */
export default function BaselinePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const s = getSession();
    if (!s || s.role !== "investigator") router.push("/");
    else setReady(true);
  }, [router]);

  async function run(e) {
    e.preventDefault();
    setError(null);
    try {
      setResult(await baselineSearch(q));
    } catch (err) {
      setError(err?.response?.data?.detail || "Search failed");
    }
  }

  if (!ready) return null;

  return (
    <div className="min-h-screen bg-ink p-6 text-[#E7ECF3]">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Baseline lookup &mdash; siloed SQL search</h1>
          <p className="text-sm text-[#7C8AA3]">
            What a keyword search over separate CDR / UPI tables returns: flat rows, one table at a time, no links.
          </p>
        </div>
        <a href="/cases" className="text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">&larr; Back to case network</a>
      </header>

      <form onSubmit={run} className="mb-4 flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. rahulk.scam or 356938035643809 or 98123"
          className="w-96 rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" />
        <button type="submit" className="rounded bg-signal px-4 py-2 text-sm font-medium text-[#0B1F3A]">Search</button>
      </form>
      {error && <p className="mb-3 text-sm text-alertred">{error}</p>}

      {result && (
        <div className="rounded-lg border border-[#1D3157] bg-[#0E1B33] p-4">
          <div className="mb-2 text-xs text-[#7C8AA3]">{result.count} row(s) for &ldquo;{result.query}&rdquo;</div>
          <table className="w-full text-left text-xs">
            <thead className="uppercase text-[#7C8AA3]">
              <tr>
                {["table", "case", "type", "timestamp", "source", "dest", "device / ref", "value", "location"].map((h) => (
                  <th key={h} className="pb-2 pr-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="mono">
              {result.rows.map((r, i) => (
                <tr key={i} className="border-t border-[#1D3157]">
                  <td className="py-1 pr-3 text-[#7C8AA3]">{r.table}</td>
                  <td className="py-1 pr-3">{r.case_id}</td>
                  <td className="py-1 pr-3">{r.record_type}</td>
                  <td className="py-1 pr-3">{r.timestamp}</td>
                  <td className="py-1 pr-3">{r.source_id}</td>
                  <td className="py-1 pr-3">{r.dest_id}</td>
                  <td className="py-1 pr-3">{r.device_or_ref}</td>
                  <td className="py-1 pr-3">{r.value}</td>
                  <td className="py-1 pr-3">{r.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
