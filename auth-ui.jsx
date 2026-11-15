import React, { createContext, useContext, useEffect, useState } from "react";

const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "TutorKid";
const AuthContext = createContext(null);

export function authFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has(CSRF_HEADER)) headers.set(CSRF_HEADER, CSRF_VALUE);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(path, { ...options, headers, credentials: "same-origin" });
}

async function readJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

export function AuthProvider({ children }) {
  const [config, setConfig] = useState(null);
  const [auth, setAuth] = useState({ loading: true, authenticated: false });
  const [error, setError] = useState("");
  const [pendingSignup, setPendingSignup] = useState(null);

  async function refresh() {
    const me = await readJson(await authFetch("/api/auth/me"));
    setAuth({ loading: false, ...me });
    return me;
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await readJson(await authFetch("/api/auth/config"));
        if (cancelled) return;
        setConfig(cfg);
        await refresh();
      } catch (err) {
        if (!cancelled) {
          setAuth({ loading: false, authenticated: false });
          setError(err.message);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function exchangeToken(idToken, { role, decision } = {}) {
    setError("");
    try {
      const response = await authFetch("/api/auth/session", {
        method: "POST",
        body: JSON.stringify({ id_token: idToken, role, decision }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.status === 409 && (body.code === "role_required" || body.code === "claim_required")) {
        setPendingSignup({
          idToken,
          email: body.email,
          name: body.name,
          code: body.code,
          unclaimedKid: body.unclaimed_kid || null,
        });
        return body;
      }
      if (!response.ok) throw new Error(body.error || "Could not sign in");
      setPendingSignup(null);
      setAuth({ loading: false, ...body });
      return body;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }

  async function signInWithDev({ email, name, role, decision }) {
    const mint = await readJson(
      await authFetch("/api/auth/dev-token", {
        method: "POST",
        body: JSON.stringify({ email, name }),
      }),
    );
    return exchangeToken(mint.id_token, { role, decision });
  }

  async function signInWithGoogle(role, decision) {
    const { initializeApp, getApps } = await import("firebase/app");
    const { getAuth, GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
    if (!config?.firebase?.apiKey) throw new Error("Firebase is not configured.");
    const app = getApps().length ? getApps()[0] : initializeApp(config.firebase);
    const authApi = getAuth(app);
    const provider = new GoogleAuthProvider();
    // Ask Chrome/Google to show the account chooser instead of silently
    // reusing the last signed-in Gmail account.
    provider.setCustomParameters({ prompt: "select_account" });
    const result = await signInWithPopup(authApi, provider);
    const idToken = await result.user.getIdToken();
    return exchangeToken(idToken, { role, decision });
  }

  function firebaseAuthErrorMessage(error) {
    const code = error?.code || "";
    if (code === "auth/email-already-in-use") return "That email already has an account. Sign in instead.";
    if (code === "auth/invalid-email") return "Enter a valid email address.";
    if (code === "auth/invalid-credential" || code === "auth/wrong-password" || code === "auth/user-not-found") {
      return "Email or password is incorrect.";
    }
    if (code === "auth/weak-password") return "Password must be at least 6 characters.";
    if (code === "auth/too-many-requests") return "Too many attempts. Try again later.";
    if (code === "auth/operation-not-allowed") {
      return "Email/password sign-in is disabled in Firebase. Enable Email/Password in the console.";
    }
    return error?.message || "Could not sign in with email and password.";
  }

  async function signInWithEmailPassword({ email, password, role, decision }) {
    const { initializeApp, getApps } = await import("firebase/app");
    const { getAuth, signInWithEmailAndPassword, sendEmailVerification, signOut } = await import(
      "firebase/auth"
    );
    if (!config?.firebase?.apiKey) throw new Error("Firebase is not configured.");
    const app = getApps().length ? getApps()[0] : initializeApp(config.firebase);
    const authApi = getAuth(app);
    let result;
    try {
      result = await signInWithEmailAndPassword(authApi, email.trim(), password);
      await result.user.reload();
    } catch (error) {
      throw new Error(firebaseAuthErrorMessage(error));
    }
    if (!result.user.emailVerified) {
      // The server only accepts verified emails; resend the link and stay signed out.
      try {
        await sendEmailVerification(result.user);
      } catch {}
      await signOut(authApi).catch(() => {});
      throw new Error(verificationSentMessage(result.user.email));
    }
    // Force a fresh token so it carries email_verified = true.
    const idToken = await result.user.getIdToken(true);
    return exchangeToken(idToken, { role, decision });
  }

  function verificationSentMessage(address) {
    return `Verify your email first: we sent a link to ${address}. Open it, then sign in.`;
  }

  async function createAccountWithEmailPassword({ email, password, name, role, decision }) {
    const { initializeApp, getApps } = await import("firebase/app");
    const {
      getAuth,
      createUserWithEmailAndPassword,
      updateProfile,
      sendEmailVerification,
      signOut,
    } = await import("firebase/auth");
    if (!config?.firebase?.apiKey) throw new Error("Firebase is not configured.");
    const app = getApps().length ? getApps()[0] : initializeApp(config.firebase);
    const authApi = getAuth(app);
    let result;
    try {
      result = await createUserWithEmailAndPassword(authApi, email.trim(), password);
      const displayName = (name || "").trim() || email.split("@")[0];
      await updateProfile(result.user, { displayName });
      await sendEmailVerification(result.user);
    } catch (error) {
      throw new Error(firebaseAuthErrorMessage(error));
    }
    // No session until the email is verified; the role is asked on first sign-in.
    await signOut(authApi).catch(() => {});
    throw new Error(verificationSentMessage(result.user.email));
  }

  async function logout() {
    await authFetch("/api/auth/logout", { method: "POST", body: "{}" });
    try {
      if (config?.firebase?.apiKey) {
        const { initializeApp, getApps } = await import("firebase/app");
        const { getAuth, signOut } = await import("firebase/auth");
        const app = getApps().length ? getApps()[0] : initializeApp(config.firebase);
        await signOut(getAuth(app));
      }
    } catch {}
    setPendingSignup(null);
    setAuth({ loading: false, authenticated: false, user: null, account: null });
  }

  async function addKid(name, email) {
    const body = await readJson(
      await authFetch("/api/auth/kids", {
        method: "POST",
        body: JSON.stringify({ name, email }),
      }),
    );
    await refresh();
    return body;
  }

  async function selectKid(accountId) {
    await readJson(
      await authFetch("/api/auth/kids/select", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      }),
    );
    return refresh();
  }

  async function decideRequest(requestId, approved) {
    await readJson(
      await authFetch(`/api/auth/guardian-requests/${requestId}/decide`, {
        method: "POST",
        body: JSON.stringify({ approved }),
      }),
    );
    return refresh();
  }

  const value = {
    config,
    auth,
    error,
    setError,
    pendingSignup,
    setPendingSignup,
    refresh,
    exchangeToken,
    signInWithDev,
    signInWithGoogle,
    signInWithEmailPassword,
    createAccountWithEmailPassword,
    logout,
    addKid,
    selectKid,
    decideRequest,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

function goTo(path) {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function AuthNavLink({ href, children }) {
  return (
    <a
      className="back-link"
      href={href}
      onClick={(event) => {
        event.preventDefault();
        goTo(href);
      }}
    >
      {children}
    </a>
  );
}

function RolePicker({ role, setRole }) {
  return (
    <div className="field">
      <label>I am a</label>
      <div className="role-toggle">
        <button
          type="button"
          className={`tab${role === "parent" ? " active" : ""}`}
          onClick={() => setRole("parent")}
        >
          Parent
        </button>
        <button
          type="button"
          className={`tab${role === "kid" ? " active" : ""}`}
          onClick={() => setRole("kid")}
        >
          Kid
        </button>
      </div>
    </div>
  );
}

function PendingSignupPanels({ pendingSignup, role, setRole, busy, error, run, exchangeToken }) {
  if (pendingSignup?.code === "role_required") {
    return (
      <main className="shell">
        <section className="card auth-card">
          <h2>Choose your role</h2>
          <p className="sub">
            Finish sign-up for {pendingSignup.email}. This only happens the first time.
          </p>
          <RolePicker role={role} setRole={setRole} />
          <button
            className="wide"
            style={{ marginTop: 14 }}
            disabled={busy}
            onClick={() => run(() => exchangeToken(pendingSignup.idToken, { role }))}
          >
            Continue
          </button>
          {error ? <div className="status auth-error">{error}</div> : null}
        </section>
      </main>
    );
  }

  if (pendingSignup?.code === "claim_required") {
    const guardians = pendingSignup.unclaimedKid?.guardians || [];
    return (
      <main className="shell">
        <section className="card auth-card">
          <h2>An account is waiting for this email</h2>
          <p className="sub">
            {pendingSignup.unclaimedKid?.name || "A kid account"} was created by a parent.
            Accept to take it over, or decline to start a new account.
          </p>
          <div className="guardian-list">
            {guardians.map((guardian) => (
              <div key={guardian.user_id} className="guardian-row">
                <strong>{guardian.name}</strong>
                <span>{guardian.email}</span>
              </div>
            ))}
          </div>
          <div className="auth-actions">
            <button
              disabled={busy}
              onClick={() =>
                run(() =>
                  exchangeToken(pendingSignup.idToken, { role: "kid", decision: "accept" }),
                )
              }
            >
              Accept account
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                run(() =>
                  exchangeToken(pendingSignup.idToken, { role: "kid", decision: "decline" }),
                )
              }
            >
              Decline and create my own
            </button>
          </div>
          {error ? <div className="status auth-error">{error}</div> : null}
        </section>
      </main>
    );
  }

  return null;
}

function useAuthForm() {
  const ctx = useAuth();
  const [role, setRole] = useState("parent");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ctx.auth.authenticated) {
      const next =
        ctx.auth.user.role === "parent" && !ctx.auth.account ? "/account" : "/";
      goTo(next);
    }
  }, [ctx.auth.authenticated, ctx.auth.account, ctx.auth.user]);

  async function run(action) {
    setBusy(true);
    ctx.setError("");
    try {
      await action();
    } catch (err) {
      ctx.setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return {
    ...ctx,
    role,
    setRole,
    email,
    setEmail,
    password,
    setPassword,
    name,
    setName,
    busy,
    run,
  };
}

function KidSwitcher() {
  const { auth, selectKid, setError } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = React.useRef(null);

  const selectedKid =
    (auth.kids || []).find((kid) => kid.account_id === auth.selected_account_id) ||
    null;
  const selectableKids = (auth.kids || []).filter((kid) => kid.selectable);
  const label = selectedKid?.kid_name || "Select kid";

  useEffect(() => {
    if (!open) return undefined;
    function onPointerDown(event) {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    function onKeyDown(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function onSelect(accountId) {
    if (accountId === auth.selected_account_id) {
      setOpen(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await selectKid(accountId);
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`kid-switcher${open ? " open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="kid-switcher-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={busy}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="kid-switcher-label">{label}</span>
        <span className="kid-switcher-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open ? (
        <div className="kid-switcher-menu" role="listbox" aria-label="Kids">
          {selectableKids.length === 0 ? (
            <div className="kid-switcher-empty">No kids yet</div>
          ) : (
            selectableKids.map((kid) => {
              const selected = kid.account_id === auth.selected_account_id;
              return (
                <button
                  key={kid.account_id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className={`kid-switcher-option${selected ? " selected" : ""}`}
                  disabled={busy}
                  onClick={() => onSelect(kid.account_id)}
                >
                  <strong>{kid.kid_name || "Kid"}</strong>
                  {kid.kid_email ? (
                    <span className="note">{kid.kid_email}</span>
                  ) : null}
                </button>
              );
            })
          )}
          <a
            className="kid-switcher-manage"
            href="/account"
            onClick={(event) => {
              event.preventDefault();
              setOpen(false);
              goTo("/account");
            }}
          >
            Manage kids…
          </a>
        </div>
      ) : null}
    </div>
  );
}

export function AccountMenu() {
  const { auth, logout, config } = useAuth();
  if (auth.loading) return <div className="local">Checking sign-in…</div>;
  if (!auth.authenticated) {
    return (
      <div className="account-menu">
        <AuthNavLink href="/signin">Sign in</AuthNavLink>
        <AuthNavLink href="/signup">Sign up</AuthNavLink>
      </div>
    );
  }
  const showKidSwitcher = auth.user.role === "parent";
  return (
    <div className="account-menu">
      {showKidSwitcher ? (
        <KidSwitcher />
      ) : auth.user.name ? (
        <span className="local kid-selected" title="Signed in as">
          {auth.user.name}
        </span>
      ) : null}
      <button type="button" className="secondary" onClick={() => logout()}>
        Log out
      </button>
      {config?.dev_mode ? <span className="note">Dev sign-in</span> : null}
    </div>
  );
}

function NavItem({ href, currentPath, children }) {
  const active =
    href === "/"
      ? currentPath === "/"
      : currentPath === href || currentPath.startsWith(`${href}/`);
  return (
    <a
      className={`site-nav-link${active ? " active" : ""}`}
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => {
        event.preventDefault();
        goTo(href);
      }}
    >
      {children}
    </a>
  );
}

export function SiteHeader() {
  const currentPath = window.location.pathname;

  return (
    <header className="top site-header">
      <a
        className="brand brand-link"
        href="/"
        onClick={(event) => {
          event.preventDefault();
          goTo("/");
        }}
      >
        <h1>LazyParent</h1>
      </a>
      <nav className="site-nav" aria-label="Main">
        <NavItem href="/chinese" currentPath={currentPath}>
          Chinese
        </NavItem>
        <NavItem href="/math" currentPath={currentPath}>
          Math
        </NavItem>
      </nav>
      <div className="top-right">
        <AccountMenu />
      </div>
    </header>
  );
}

export function SignInPage() {
  const {
    config,
    auth,
    error,
    pendingSignup,
    signInWithDev,
    signInWithGoogle,
    signInWithEmailPassword,
    exchangeToken,
    role,
    setRole,
    email,
    setEmail,
    password,
    setPassword,
    name,
    setName,
    busy,
    run,
  } = useAuthForm();

  if (auth.loading || !config) {
    return (
      <main className="shell">
        <section className="card auth-card"><p className="sub">Loading sign-in…</p></section>
      </main>
    );
  }

  if (
    pendingSignup?.code === "role_required" ||
    pendingSignup?.code === "claim_required"
  ) {
    return (
      <PendingSignupPanels
        pendingSignup={pendingSignup}
        role={role}
        setRole={setRole}
        busy={busy}
        error={error}
        run={run}
        exchangeToken={exchangeToken}
      />
    );
  }

  return (
    <main className="shell">
      <SiteHeader />
      <section className="card auth-card">
        <h2>Sign in</h2>
        <p className="sub">Use your existing account. New here? Create one on Sign up.</p>

        {config.dev_mode ? (
          <>
            <RolePicker role={role} setRole={setRole} />
            <div className="field">
              <label htmlFor="dev-name">Name</label>
              <input id="dev-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex" />
            </div>
            <div className="field">
              <label htmlFor="dev-email">Email</label>
              <input
                id="dev-email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="alex@example.com"
              />
            </div>
            <button
              className="wide"
              disabled={busy || !email}
              onClick={() => run(() => signInWithDev({ email, name, role }))}
            >
              {busy ? "Signing in…" : "Continue (local dev)"}
            </button>
            <p className="note">AUTH_DEV_MODE is on. Firebase is not required for local testing.</p>
          </>
        ) : (
          <>
            <button
              className="wide"
              disabled={busy}
              onClick={() => run(() => signInWithGoogle())}
            >
              Continue with Google
            </button>
            <div className="or">OR EMAIL AND PASSWORD</div>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Your password"
              />
            </div>
            <button
              className="wide"
              disabled={busy || !email || !password}
              onClick={() =>
                run(() => signInWithEmailPassword({ email, password }))
              }
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </>
        )}

        {error ? <div className="status auth-error">{error}</div> : null}
        <p className="note">
          No account yet? <AuthNavLink href="/signup">Sign up</AuthNavLink>
        </p>
      </section>
    </main>
  );
}

export function SignUpPage() {
  const {
    config,
    auth,
    error,
    pendingSignup,
    signInWithDev,
    signInWithGoogle,
    createAccountWithEmailPassword,
    exchangeToken,
    role,
    setRole,
    email,
    setEmail,
    password,
    setPassword,
    name,
    setName,
    busy,
    run,
  } = useAuthForm();

  if (auth.loading || !config) {
    return (
      <main className="shell">
        <section className="card auth-card"><p className="sub">Loading sign-up…</p></section>
      </main>
    );
  }

  if (
    pendingSignup?.code === "role_required" ||
    pendingSignup?.code === "claim_required"
  ) {
    return (
      <PendingSignupPanels
        pendingSignup={pendingSignup}
        role={role}
        setRole={setRole}
        busy={busy}
        error={error}
        run={run}
        exchangeToken={exchangeToken}
      />
    );
  }

  return (
    <main className="shell">
      <SiteHeader />
      <section className="card auth-card">
        <h2>Create account</h2>
        <p className="sub">Choose your role, then continue with Google or email.</p>

        <RolePicker role={role} setRole={setRole} />

        {config.dev_mode ? (
          <>
            <div className="field">
              <label htmlFor="signup-dev-name">Name</label>
              <input
                id="signup-dev-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Alex"
              />
            </div>
            <div className="field">
              <label htmlFor="signup-dev-email">Email</label>
              <input
                id="signup-dev-email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="alex@example.com"
              />
            </div>
            <button
              className="wide"
              disabled={busy || !email}
              onClick={() => run(() => signInWithDev({ email, name, role }))}
            >
              {busy ? "Creating…" : "Create account (local dev)"}
            </button>
            <p className="note">AUTH_DEV_MODE is on. Firebase is not required for local testing.</p>
          </>
        ) : (
          <>
            <button
              className="wide"
              disabled={busy}
              onClick={() => run(() => signInWithGoogle(role))}
            >
              Continue with Google
            </button>
            <div className="or">OR EMAIL AND PASSWORD</div>
            <div className="field">
              <label htmlFor="signup-name">Name</label>
              <input
                id="signup-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Alex"
                autoComplete="name"
              />
            </div>
            <div className="field">
              <label htmlFor="signup-email">Email</label>
              <input
                id="signup-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="field">
              <label htmlFor="signup-password">Password</label>
              <input
                id="signup-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 6 characters"
              />
            </div>
            <button
              className="wide"
              disabled={busy || !email || !password}
              onClick={() =>
                run(() =>
                  createAccountWithEmailPassword({ email, password, name, role }),
                )
              }
            >
              {busy ? "Creating…" : "Create account"}
            </button>
          </>
        )}

        {error ? <div className="status auth-error">{error}</div> : null}
        <p className="note">
          Already have an account? <AuthNavLink href="/signin">Sign in</AuthNavLink>
        </p>
      </section>
    </main>
  );
}

export function AccountPage() {
  const { auth, addKid, selectKid, decideRequest, error, setError, refresh } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  if (auth.loading) {
    return <main className="shell"><section className="card auth-card"><p className="sub">Loading…</p></section></main>;
  }
  if (!auth.authenticated) {
    window.history.pushState(null, "", "/signin");
    window.dispatchEvent(new PopStateEvent("popstate"));
    return null;
  }
  if (auth.user.role !== "parent") {
    return (
      <main className="shell">
        <section className="card auth-card">
          <h2>Your account</h2>
          <p className="sub">Signed in as {auth.user.name} ({auth.user.email}).</p>
          <GuardianRequests />
        </section>
      </main>
    );
  }

  async function onAdd(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await addKid(name, email);
      if (result.status === "pending_approval") {
        setMessage("Waiting for approval from the kid or an existing guardian.");
      } else if (result.status === "already_guardian") {
        setMessage("You already guard this kid. Selected.");
      } else {
        setMessage("Kid account created and selected.");
        setName("");
        setEmail("");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <SiteHeader />
      <section className="card auth-card">
        <h2>Select or add a kid</h2>
        <p className="sub">Parents work inside a kid account. Choose one below or add a new kid by name and email.</p>

        <div className="kid-list">
          {(auth.kids || []).map((kid) => (
            <div className="kid-row" key={`${kid.account_id}-${kid.status}`}>
              <div>
                <strong>{kid.kid_name || "Kid"}</strong>
                <div className="note">
                  {kid.kid_email || "email released"} · {kid.status.replaceAll("_", " ")}
                </div>
              </div>
              {kid.selectable ? (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || auth.selected_account_id === kid.account_id}
                  onClick={() =>
                    (async () => {
                      setBusy(true);
                      try {
                        await selectKid(kid.account_id);
                        setMessage("Kid selected.");
                      } catch (err) {
                        setError(err.message);
                      } finally {
                        setBusy(false);
                      }
                    })()
                  }
                >
                  {auth.selected_account_id === kid.account_id ? "Selected" : "Select"}
                </button>
              ) : (
                <span className="note">{kid.status.replaceAll("_", " ")}</span>
              )}
            </div>
          ))}
          {(auth.kids || []).length === 0 ? (
            <p className="note">No kids yet. Add the first one below.</p>
          ) : null}
        </div>

        <form onSubmit={onAdd}>
          <div className="field">
            <label htmlFor="kid-name">Kid name</label>
            <input id="kid-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="kid-email">Kid email</label>
            <input
              id="kid-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <button className="wide" disabled={busy}>
            {busy ? "Saving…" : "Add kid"}
          </button>
        </form>

        <GuardianRequests />
        {message ? <div className="status">{message}</div> : null}
        {error ? <div className="status auth-error">{error}</div> : null}
        <button type="button" className="quiet" onClick={() => refresh()}>
          Refresh
        </button>
      </section>
    </main>
  );
}

function GuardianRequests() {
  const { auth, decideRequest, setError } = useAuth();
  const requests = auth.pending_guardian_requests || [];
  if (!requests.length) return null;
  return (
    <div className="guardian-requests">
      <h2>Guardian requests</h2>
      <p className="sub">Approve parents who asked to join this kid account.</p>
      {requests.map((request) => (
        <div className="kid-row" key={request.request_id}>
          <div>
            <strong>{request.requester_name}</strong>
            <div className="note">{request.requester_email}</div>
          </div>
          <div className="auth-actions">
            <button type="button" onClick={() => decideRequest(request.request_id, true).catch((e) => setError(e.message))}>
              Approve
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => decideRequest(request.request_id, false).catch((e) => setError(e.message))}
            >
              Decline
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
