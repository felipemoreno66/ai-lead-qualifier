import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApplyForm } from "@/features/apply/apply-form";
import { publicWorkspaceConfigSchema } from "@/lib/api/schemas";
import { publicApiBase, publicFetch } from "@/lib/api/server";
import { pickLocale, ui } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const config = await publicFetch(
    `/api/workspaces/${(await params).slug}/public-config`,
    publicWorkspaceConfigSchema,
  );
  return { title: config ? ui(config.default_language).applyTitle(config.name) : "Apply" };
}

export default async function ApplyPage({
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
  return (
    <ApplyForm
      config={config}
      apiBase={publicApiBase()}
      initialLocale={pickLocale(lang, config.languages, config.default_language)}
    />
  );
}
