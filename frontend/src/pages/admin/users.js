import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { getSession, clearSession, listUsers, createUser, assignCase } from "@/services/api";

export default function AdminUsersPage() {
  const router = useRouter();
  const [session, setSession] = useState(null);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ username: "", password: "", role: "investigator", full_name: "" });
  const [assignForm, setAssignForm] = useState({ userId: "", caseId: "" });
  const [error, setError] = useState(null);

  useEffect(() => {
    const s = getSession();
    if (!s || s.role !== "admin") {
      router.push("/");
      return;
    }
    setSession(s);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function refresh() {
    setUsers(await listUsers());
  }

  async function handleCreate(e) {
    e.preventDefault();
    setError(null);
    try {
      await createUser(form);
      setForm({ username: "", password: "", role: "investigator", full_name: "" });
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create user.");
    }
  }

  async function handleAssign(e) {
    e.preventDefault();
    setError(null);
    try {
      await assignCase(assignForm.userId, assignForm.caseId);
      setAssignForm({ userId: "", caseId: "" });
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to assign case.");
    }
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-ink p-6 text-[#E7ECF3]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Sandhan &mdash; Admin</h1>
          <p className="text-sm text-[#7C8AA3]">Account &amp; access management only. No case content is visible here.</p>
        </div>
        <div className="flex gap-4">
          <a href="/admin/audit" className="text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">System audit log</a>
          <button onClick={() => { clearSession(); router.push("/"); }} className="text-sm text-[#9AA7BD] hover:text-[#E7ECF3]">
            Sign out
          </button>
        </div>
      </header>

      {error && <p className="mb-4 text-sm text-alertred">{error}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-[#1D3157] bg-[#0E1B33] p-5">
          <h2 className="mb-3 text-sm font-medium">Create user</h2>
          <form onSubmit={handleCreate} className="flex flex-col gap-3">
            <input placeholder="Username" value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" required />
            <input placeholder="Password" type="password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" required />
            <input placeholder="Full name" value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" />
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm">
              <option value="investigator">Investigator</option>
              <option value="admin">Admin</option>
            </select>
            <button type="submit" className="rounded bg-signal px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90">
              Create
            </button>
          </form>
        </section>

        <section className="rounded-lg border border-[#1D3157] bg-[#0E1B33] p-5">
          <h2 className="mb-3 text-sm font-medium">Assign case to investigator</h2>
          <form onSubmit={handleAssign} className="flex flex-col gap-3">
            <select value={assignForm.userId} onChange={(e) => setAssignForm({ ...assignForm, userId: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" required>
              <option value="">Select investigator</option>
              {users.filter((u) => u.role === "investigator").map((u) => (
                <option key={u.id} value={u.id}>{u.username}</option>
              ))}
            </select>
            <input placeholder="Case ID (new e.g. CASE-2026-0004, or historical e.g. CASE0080)" value={assignForm.caseId}
              onChange={(e) => setAssignForm({ ...assignForm, caseId: e.target.value })}
              className="rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm" required />
            <button type="submit" className="rounded bg-verified px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90">
              Assign
            </button>
            <p className="text-xs text-[#6C7C97]">
              Assigning a historical case ID lets an investigator open that case and see its links. The
              assignment takes effect immediately (no re-login needed).
            </p>
          </form>
        </section>
      </div>

      <section className="mt-6 rounded-lg border border-[#1D3157] bg-[#0E1B33] p-5">
        <h2 className="mb-3 text-sm font-medium">Users</h2>
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-[#7C8AA3]">
            <tr>
              <th className="pb-2">Username</th>
              <th className="pb-2">Role</th>
              <th className="pb-2">Full name</th>
              <th className="pb-2">Assigned cases</th>
            </tr>
          </thead>
          <tbody className="mono text-xs">
            {users.map((u) => (
              <tr key={u.id} className="border-t border-[#1D3157]">
                <td className="py-2">{u.username}</td>
                <td className="py-2">{u.role}</td>
                <td className="py-2">{u.full_name}</td>
                <td className="py-2">{u.assigned_case_ids.join(", ") || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
