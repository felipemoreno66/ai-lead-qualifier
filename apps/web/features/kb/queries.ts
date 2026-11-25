import { bffGet, bffPost } from "@/lib/api/client";
import { kbChatEntriesSchema, kbChatEntrySchema } from "@/lib/api/schemas";

export const askDocs = (slug: string, question: string) =>
  bffPost(`/bff/kb/${slug}/ask`, { question }, kbChatEntrySchema);
export const fetchRecentQuestions = (slug: string) =>
  bffGet(`/bff/kb/${slug}/queries`, kbChatEntriesSchema);
export const recentKey = (slug: string) => ["kb", slug, "recent"] as const;
