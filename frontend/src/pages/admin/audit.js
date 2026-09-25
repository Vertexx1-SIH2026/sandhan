import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { getSession, clearSession, getSystemAuditLog } from "@/services/api";

export default function AdminAuditPage() {
  const router = useRouter();
  const [session, setSession] = useState(null);
  const [rows, setRows] = useState([]);

  useEffect(() => {
    const s = getSession();
    if (!s || s.role !== "admin") {
      router.push("/");
      return;
    }
    setSession(s);
    getSystemAuditLog().then(setRows);
  }, [router]);

  if (!session) return null;

  return (
    <div className="min-h-screen bg-ink p-6 text-[#E7ECF3]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">System audit log</h1>
          <p className="text-sm text-[#7C8AA3]">Logins, account creation, role changes, export events. No case content.</p>
        </div>
        <div className="flex gap-4">
          <a href="/admin/users" className="text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">Users</a>
          <button onClick={() => { clearSession(); router.push("/"); }} className="text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">
            Sign out
          </button>
        </div>
      </header>

      <section className="rounded-lg border border-[#1D3157] bg-[#0E1B33] p-5">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-[#7C8AA3]">
            <tr>
              <th className="pb-2">Timestamp</th>
              <th className="pb-2">Event</th>
              <th className="pb-2">Actor</th>
              <th className="pb-2">Detail</th>
            </tr>
          </thead>
          <tbody className="mono text-xs">
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-[#1D3157] align-top">
                <td className="py-2 whitespace-nowrap">{r.timestamp}</td>
                <td className="py-2">{r.event_type}</td>
                <td className="py-2">{(r.actor_id || "-").slice(0, 8)}</td>
                <td className="py-2">{JSON.stringify(r.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
