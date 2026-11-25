import {
  agentRunsSchema,
  leadDetailSchema,
  leadListSchema,
  publicWorkspaceConfigSchema,
  retriggerResultSchema,
  reviewRequestSchema,
  reviewResultSchema,
  workspaceSummariesSchema,
} from "contracts";
import type { z } from "zod";

export {
  agentRunsSchema,
  leadDetailSchema,
  leadListSchema,
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
export type ReviewInput = z.input<typeof reviewRequestSchema>;
