import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, getToken, setToken, tokenExpiry } from "./api/client";
import { useHealth, useStatus } from "./api/hooks";
import { Assistant } from "./components/assistant/Assistant";
import { Wordmark } from "./components/Brand";
import { Preloader } from "./components/Preloader";
import { Shell } from "./components/shell/Shell";
import { PageSkeleton } from "./components/ui";
import Home from "./pages/Home";

const Orders = lazy(() => import("./pages/Orders"));
const Team = lazy(() => import("./pages/Team"));
const Clients = lazy(() => import("./pages/Clients"));
const Enquiries = lazy(() => import("./pages/Enquiries"));
const Payments = lazy(() => import("./pages/Payments"));
const Returns = lazy(() => import("./pages/Returns"));

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
        <Wordmark variant="letters" height={30} />
        <h1>Operations dashboard</h1>
        <p>Enter the passcode to see live orders and who needs to act.</p>
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
          <Route path="/" element={<Home />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/team" element={<Team />} />
          <Route path="/clients" element={<Clients />} />
          <Route path="/enquiries" element={<Enquiries />} />
          <Route path="/payments" element={<Payments />} />
          <Route path="/returns" element={<Returns />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
    {!loading && <Assistant />}
    {loading && <Preloader status={status.data ?? (status.error ? ({ sources: {} } as never) : undefined)} onDone={finish} />}
    </>
  );
}

/** A saved token counts only until it expires (the server issues them for TOKEN_HOURS, 24 h in production). */
function hasLiveToken(): boolean {
  const token = getToken();
  if (!token) return false;
  if (tokenExpiry(token) > Date.now()) return true;
  setToken(null);
  return false;
}

export default function App() {
  const health = useHealth();
  const [signedIn, setSignedIn] = useState(hasLiveToken);
  useEffect(() => {
    const out = () => {
      setToken(null);
      setSignedIn(false);
    };
    window.addEventListener("flo:signed-out", out);
    return () => window.removeEventListener("flo:signed-out", out);
  }, []);
  // A tab left open past the token's expiry asks for the password again, without waiting for a failed request.
  useEffect(() => {
    if (!signedIn) return;
    const exp = tokenExpiry(getToken());
    if (!exp) return;
    const id = window.setTimeout(() => window.dispatchEvent(new Event("flo:signed-out")), Math.max(0, Math.min(exp - Date.now(), 2 ** 31 - 1)));
    return () => window.clearTimeout(id);
  }, [signedIn]);
  // Decide nothing until the server says whether a password is needed, so the preloader never shows before it.
  if (health.isPending) return null;
  if (health.data?.auth_required && !signedIn) {
    return (
      <SignIn
        onDone={() => {
          try {
            sessionStorage.removeItem("flowing-intro"); // the preloader plays right after every sign-in
          } catch {
            /* ignore */
          }
          setSignedIn(true);
        }}
      />
    );
  }
  return <Dashboard />;
}
