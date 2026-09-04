import { useState } from "react";
import "./gate.css";
import { api } from "./lib/client";

type Props = { onSuccess: () => void };

/**
 * Two accounts, no signup, no recovery. A failed attempt says nothing about
 * *why* it failed -- the backend returns the same generic rejection whether
 * the username or the password was wrong, and this is where that stays
 * generic on the way back out to the screen.
 */
export function Login({ onSuccess }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(username, password);
      onSuccess();
    } catch {
      // Deliberately uninformative. It does not say which field was wrong,
      // or whether the account exists at all.
      setError("login failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="gate__login" onSubmit={submit}>
      <label className="gate__field">
        <span className="label">user</span>
        <input
          className="gate__input"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
        />
      </label>
      <label className="gate__field">
        <span className="label">pass</span>
        <input
          className="gate__input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </label>
      <button className="gate__submit" type="submit" disabled={busy}>
        sign in
      </button>
      {error && (
        <p className="gate__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
