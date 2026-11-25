import {
  agentRunsSchema,
  kbChatEntriesSchema,
  kbChatEntrySchema,
  leadDetailSchema,
  leadListSchema,
  metricsSchema,
  publicWorkspaceConfigSchema,
  retriggerResultSchema,
  reviewRequestSchema,
  reviewResultSchema,
  workspaceSummariesSchema,
} from "contracts";
import { z } from "zod";

export {
  agentRunsSchema,
  kbChatEntriesSchema,
  kbChatEntrySchema,
  leadDetailSchema,
  leadListSchema,
  metricsSchema,
  publicWorkspaceConfigSchema,
  retriggerResultSchema,
  reviewRequestSchema,
  reviewResultSchema,
  workspaceSummariesSchema,
};
export type { LeadDetailSchema as LeadDetail, LeadListSchema as LeadList } from "contracts";
export type LeadListItem = import("contracts").LeadListSchema["items"][number];
export type WorkspaceSummary = import("contracts").WorkspaceSummariesSchema[number];
export type Message = import("contracts").LeadDetailSchema["messages"][number];
export type Breakdown = import("contracts").LeadDetailSchema["breakdown"][number];
export type AgentRun = z.infer<typeof agentRunsSchema>[number];
export type Metrics = z.infer<typeof metricsSchema>;
export type ReviewInput = z.input<typeof reviewRequestSchema>;

export type KbEntry = z.infer<typeof kbChatEntrySchema>;
export type KbCitation = KbEntry["citations"][number];

/** Body of "Ask the docs": mirrors the agent's limits (3 to 500 characters). */
export const kbAskRequestSchema = z.object({
  question: z.string().trim().min(3).max(500),
  language: z
    .string()
    .regex(/^[a-z]{2}$/)
    .optional(),
});
