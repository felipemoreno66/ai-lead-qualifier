import type { Metadata } from "next";
import Link from "next/link";
import { Check } from "lucide-react";
import { notFound } from "next/navigation";
import { publicWorkspaceConfigSchema } from "@/lib/api/schemas";
import { publicFetch } from "@/lib/api/server";
import { pickLocale, ui } from "@/lib/i18n";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Application received" };

export default async function ThanksPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ ref?: string; lang?: string }>;
}) {
  const { slug } = await params;
  const { ref, lang } = await searchParams;
  const config = await publicFetch(`/api/workspaces/${slug}/public-config`, publicWorkspaceConfigSchema);
  if (!config) notFound();
  const locale = pickLocale(lang, config.languages, config.default_language);
  const t = ui(locale);
  const reference = ref && /^[A-Z0-9-]{4,20}$/.test(ref) ? ref : null;
  return (
    <div className="success" lang={locale}>
      <div className="seal">
        <Check size={34} strokeWidth={1.8} aria-hidden="true" />
      </div>
      <h1>{t.thanksTitle}</h1>
      {reference && (
        <p className="refrow">
          {t.reference}: <b className="num">{reference}</b>
        </p>
      )}
      <p className="lead">{t.thanksBody}</p>
      <Link href={`/privacy/${slug}?lang=${locale}`}>{t.readNotice}</Link>
    </div>
  );
}
