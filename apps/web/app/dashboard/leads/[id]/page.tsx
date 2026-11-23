import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { z } from "zod";
import { LeadDetailView } from "@/features/leads/lead-detail-view";
import { leadKey } from "@/features/leads/queries";
import { leadDetailSchema } from "@/lib/api/schemas";
import { AgentError, adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const parsed = z.uuid().safeParse((await params).id);
  if (!parsed.success) notFound();
  const client = new QueryClient();
  try {
    await client.fetchQuery({
      queryKey: leadKey(parsed.data),
      queryFn: () => adminFetch(`/admin/leads/${parsed.data}`, leadDetailSchema),
    });
  } catch (error) {
    if (error instanceof AgentError && error.status === 404) notFound();
    // Otherwise let the client component show the error state with a retry button.
  }
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <LeadDetailView id={parsed.data} />
    </HydrationBoundary>
  );
}
