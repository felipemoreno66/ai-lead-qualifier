"use client";

import { useRef, useState } from "react";

type Props = { next: string };

const GENERIC = "The email or password is not right. Check both and try again.";

/** Operator sign-in. Every failure reads the same, so the form never says which half was wrong. */
export function LoginForm({ next }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const alertRef = useRef<HTMLParagraphElement>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/sign-in/email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: data.get("email"), password: data.get("password") }),
      });
      if (res.ok) {
        // A full navigation, so the new session cookie is sent to the server-rendered page.
        window.location.assign(next);
        return;
      }
      setError(
        res.status === 429
          ? "Too many attempts. Wait a few minutes before trying again."
          : res.status === 503
            ? "Sign-in is not set up on this server."
            : GENERIC,
      );
    } catch {
      setError("Could not reach the server. Check your connection and try again.");
    }
    setSubmitting(false);
    requestAnimationFrame(() => alertRef.current?.focus());
  }

  return (
    <form className="form" onSubmit={onSubmit} aria-busy={submitting}>
      {error && (
        <p className="form-alert" role="alert" tabIndex={-1} ref={alertRef}>
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="login-email">Email</label>
        <input id="login-email" name="email" type="email" autoComplete="username" required />
      </div>
      <div className="field">
        <label htmlFor="login-password">Password</label>
        <input id="login-password" name="password" type="password" autoComplete="current-password" required />
      </div>
      <button className="btn primary big" type="submit" disabled={submitting}>
        {submitting ? "Signing in" : "Sign in"}
      </button>
    </form>
  );
}
