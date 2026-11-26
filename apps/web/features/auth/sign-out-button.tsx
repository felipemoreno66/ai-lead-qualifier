"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SignOutButton() {
  const router = useRouter();
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
      router.replace("/login");
      router.refresh(); // drop the cached pages of the signed-in session
    }
  }
  return (
    <button type="button" className="signout" onClick={signOut} disabled={busy}>
      <LogOut className="ic" strokeWidth={1.6} aria-hidden="true" />
      <span>Sign out</span>
    </button>
  );
}
