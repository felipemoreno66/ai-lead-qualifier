"use client";

import { ChartColumn, FileText, List, MessageCircle } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SignOutButton } from "@/features/auth/sign-out-button";

type Props = { applyHref: string | null; showSignOut?: boolean };

export function AppHeader({ applyHref, showSignOut = false }: Props) {
  const pathname = usePathname();
  const onMetrics = pathname.startsWith("/dashboard/metrics");
  const onAsk = pathname.startsWith("/dashboard/ask");
  const onLeads = pathname.startsWith("/dashboard") && !onMetrics && !onAsk;
  const links = (compact: boolean) => (
    <>
      <Link href="/dashboard" aria-current={onLeads ? "page" : undefined}>
        <List className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Leads</span>
      </Link>
      <Link href="/dashboard/ask" aria-current={onAsk ? "page" : undefined}>
        <MessageCircle className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Ask</span>
      </Link>
      <Link href="/dashboard/metrics" aria-current={onMetrics ? "page" : undefined}>
        <ChartColumn className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Metrics</span>
      </Link>
      {applyHref && (
        <Link href={applyHref}>
          <FileText className="ic" strokeWidth={1.6} aria-hidden="true" />
          <span>{compact ? "Form" : "Application form"}</span>
        </Link>
      )}
    </>
  );
  return (
    <>
      <header className="top">
        <Link className="brand" href="/dashboard">
          <span className="mark" aria-hidden="true" />
          Lead Qualifier
        </Link>
        <nav className="dnav" aria-label="Main">
          {links(false)}
        </nav>
        {showSignOut && <SignOutButton />}
      </header>
      <nav className="tabs" aria-label="Main">
        {links(true)}
      </nav>
    </>
  );
}
