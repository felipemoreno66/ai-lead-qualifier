import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PublicShell } from "@/components/public-shell";
import { publicWorkspaceConfigSchema } from "@/lib/api/schemas";
import { publicFetch } from "@/lib/api/server";
import { localized, pickLocale, ui } from "@/lib/i18n";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Privacy notice" };

export default async function PrivacyPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ lang?: string }>;
}) {
  const { slug } = await params;
  const { lang } = await searchParams;
  const config = await publicFetch(`/api/workspaces/${slug}/public-config`, publicWorkspaceConfigSchema);
  if (!config) notFound();
  const locale = pickLocale(lang, config.languages, config.default_language);
  const t = ui(locale);
  const { privacy } = config;
  return (
    <PublicShell name={config.name}>
      <div className="apply" lang={locale}>
        <div className="intro">
          <h1>{t.privacyTitle}</h1>
        </div>
        <p className="lead">{localized(privacy.notice, locale, config.default_language)}</p>
        <dl className="kv">
          <dt>{t.controller}</dt>
          <dd>{privacy.controller}</dd>
          <dt>{t.version}</dt>
          <dd className="num">{privacy.version}</dd>
          <dt>{t.retentionLabel}</dt>
          <dd>{t.retention(privacy.retention_days)}</dd>
        </dl>
        <p style={{ marginTop: 32 }}>
          <Link href={`/w/${slug}/apply?lang=${locale}`}>{t.backToForm}</Link>
        </p>
      </div>
    </PublicShell>
  );
}
