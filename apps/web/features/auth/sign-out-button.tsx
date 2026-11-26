"use client";

import { LogOut } from "lucide-react";
import { useState } from "react";

// A full navigation drops every client-side cache of the signed-in session.
const LOGIN_PATH = "/login";

export function SignOutButton() {
  const [busy, setBusy] = useState(false);
  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/sign-out", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } finally {
      window.location.assign(LOGIN_PATH);
    }
  }
  return (
    <button type="button" className="signout" onClick={signOut} disabled={busy}>
      <LogOut className="ic" strokeWidth={1.6} aria-hidden="true" />
      <span>Sign out</span>
    </button>
  );
}
