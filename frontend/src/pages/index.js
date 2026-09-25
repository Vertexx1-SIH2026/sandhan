import { useState } from "react";
import { useRouter } from "next/router";
import { login } from "@/services/api";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await login(username, password);
      router.push(res.role === "admin" ? "/admin/users" : "/cases");
    } catch (err) {
      setError("Incorrect username or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4">
      <div className="w-full max-w-sm rounded-lg border border-[#1D3157] bg-[#0E1B33] p-8">
        <h1 className="text-xl font-semibold text-[#E7ECF3]">Sandhan</h1>
        <p className="mt-1 text-sm text-[#7C8AA3]">Criminal network analysis &mdash; investigator sign-in</p>

        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-3">
          <div>
            <label className="block text-xs text-[#9AA7BD]">Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 w-full rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm text-[#E7ECF3]"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-[#9AA7BD]">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded border border-[#2C4266] bg-[#0B1F3A] px-3 py-2 text-sm text-[#E7ECF3]"
            />
          </div>

          {error && <p className="text-sm text-alertred">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="mt-2 rounded bg-signal px-4 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-xs text-[#6C7C97]">
          Demo accounts (after running <span className="mono">scripts/seed_db.py</span>):
          <br />admin / admin123 &middot; investigator1 / invest123
        </p>
      </div>
    </div>
  );
}
