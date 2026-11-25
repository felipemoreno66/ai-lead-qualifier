import { bffGet, bffPost } from "@/lib/api/client";
import {
  agentRunsSchema,
  leadDetailSchema,
  leadListSchema,
  reviewResultSchema,
  workspaceSummariesSchema,
  type ReviewInput,
} from "@/lib/api/schemas";
import { toApiParams, type LeadFilters } from "@/lib/leads/filters";

export const fetchLeads = (filters: LeadFilters) =>
  bffGet(`/bff/leads?${toApiParams(filters)}`, leadListSchema);
export const fetchLead = (id: string) => bffGet(`/bff/leads/${id}`, leadDetailSchema);
export const fetchRuns = (id: string) => bffGet(`/bff/leads/${id}/runs`, agentRunsSchema);
export const fetchWorkspaces = () => bffGet("/bff/workspaces", workspaceSummariesSchema);
export const submitReview = (id: string, review: ReviewInput) =>
  bffPost(`/bff/leads/${id}/review`, review, reviewResultSchema);
export const leadKey = (id: string) => ["lead", id] as const;
export const runsKey = (id: string) => ["lead", id, "runs"] as const;
