"use client";

import { FileText, List, MessageCircle } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type Props = { applyHref: string | null };

export function AppHeader({ applyHref }: Props) {
  const pathname = usePathname();
  const onAsk = pathname.startsWith("/dashboard/ask");
  const onLeads = pathname.startsWith("/dashboard") && !onAsk;
  const links = (
    <>
      <Link href="/dashboard" aria-current={onLeads ? "page" : undefined}>
        <List className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Leads</span>
      </Link>
      <Link href="/dashboard/ask" aria-current={onAsk ? "page" : undefined}>
        <MessageCircle className="ic" strokeWidth={1.6} aria-hidden="true" />
        <span>Ask</span>
      </Link>
      {applyHref && (
        <Link href={applyHref}>
          <FileText className="ic" strokeWidth={1.6} aria-hidden="true" />
          <span>Application form</span>
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
          {links}
        </nav>
      </header>
      <nav className="tabs" aria-label="Main">
        {links}
      </nav>
    </>
  );
}
