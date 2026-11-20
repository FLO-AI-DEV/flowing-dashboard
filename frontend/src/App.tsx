import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, getToken, setToken } from "./api/client";
import { useHealth, useStatus } from "./api/hooks";
import { Assistant } from "./components/assistant/Assistant";
import { Wordmark } from "./components/Brand";
import { Preloader } from "./components/Preloader";
import { Shell } from "./components/shell/Shell";
import { PageSkeleton } from "./components/ui";
import Overview from "./pages/Overview";

const Orders = lazy(() => import("./pages/Orders"));
const Vendors = lazy(() => import("./pages/Vendors"));
const OrderToVendors = lazy(() => import("./pages/OrderToVendors"));
const Dues = lazy(() => import("./pages/Dues"));
const Sheets = lazy(() => import("./pages/Sheets"));

function SignIn({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ token: string }>("/auth/login", undefined, { method: "POST", body: JSON.stringify({ passcode: code }) });
      setToken(r.token);
      onDone();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="signin">
      <form onSubmit={submit}>
        <Wordmark variant="letters" height={30} wing />
        <h1>Operations dashboard</h1>
        <p>Enter the team passcode to see live Flo-Wing orders, vendors and dues.</p>
        <input className="field" type="password" autoComplete="current-password" placeholder="Passcode" value={code} onChange={(e) => setCode(e.target.value)} autoFocus aria-label="Passcode" />
        {err && <div className="err" role="alert">{err}</div>}
        <button className="btn primary" type="submit" disabled={busy || !code}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

/** The intro plays on the first visit of a browser session; ?nointro skips it (automated checks). */
function introWanted(): boolean {
  try {
    if (new URLSearchParams(window.location.search).has("nointro")) return false;
    return sessionStorage.getItem("flowing-intro") !== "1";
  } catch {
    return true;
  }
}

function Dashboard() {
  const status = useStatus();
  const [loading, setLoading] = useState(introWanted);
  const finish = () => {
    try {
      sessionStorage.setItem("flowing-intro", "1");
    } catch {
      /* ignore */
    }
    setLoading(false);
  };
  return (
    <>
      <Shell>
        <Suspense fallback={<div className="page"><PageSkeleton /></div>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/vendors" element={<Vendors />} />
            <Route path="/order-to-vendors" element={<OrderToVendors />} />
            <Route path="/dues" element={<Dues />} />
            <Route path="/sheets" element={<Sheets />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Shell>
      <Assistant />
      {loading &&<Preloader status={status.data ?? (status.error ? ({ sources: {} } as never) : undefined)} onDone={finish} />}
    </>
  );
}

export default function App() {
  const health = useHealth();
  const [signedIn, setSignedIn] = useState(() => !!getToken());
  useEffect(() => {
    const out = () => {
      setToken(null);
      setSignedIn(false);
    };
    window.addEventListener("flo:signed-out", out);
    return () => window.removeEventListener("flo:signed-out", out);
  }, []);
  if (health.data?.auth_required && !signedIn) return <SignIn onDone={() => setSignedIn(true)} />;
  return <Dashboard />;
}
