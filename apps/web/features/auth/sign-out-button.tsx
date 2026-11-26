"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useState } from "react";

export function SignOutButton() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function signOut() {
    setBusy(true);
    setFailed(false);
    try {
      const res = await fetch("/api/auth/sign-out", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!res.ok) throw new Error("sign-out failed");
    } catch {
      // Still signed in: say so instead of pretending, and keep the page as it is.
      setFailed(true);
      setBusy(false);
      return;
    }
    queryClient.clear(); // no signed-in data stays in the client cache
    // A hard navigation also drops the router cache; replace keeps the dashboard out of history.
    window.location.replace("/login");
  }

  return (
    <>
      <button type="button" className="signout" onClick={signOut} disabled={busy}>
        <LogOut className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Sign out</span>
      </button>
      {failed && (
        <span className="field-error" role="alert">
          Could not sign out. Try again.
        </span>
      )}
    </>
  );
}
