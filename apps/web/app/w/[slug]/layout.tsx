import { notFound } from "next/navigation";
import { PublicShell } from "@/components/public-shell";
import { publicWorkspaceConfigSchema } from "@/lib/api/schemas";
import { publicFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export default async function PublicLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const config = await publicFetch(`/api/workspaces/${slug}/public-config`, publicWorkspaceConfigSchema);
  if (!config) notFound();
  return <PublicShell name={config.name}>{children}</PublicShell>;
}
