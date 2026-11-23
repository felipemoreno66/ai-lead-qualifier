import { bffGet } from "@/lib/api/client";
import { leadDetailSchema, leadListSchema, workspaceSummariesSchema } from "@/lib/api/schemas";
import { toApiParams, type LeadFilters } from "@/lib/leads/filters";

export const fetchLeads = (filters: LeadFilters) =>
  bffGet(`/bff/leads?${toApiParams(filters)}`, leadListSchema);
export const fetchLead = (id: string) => bffGet(`/bff/leads/${id}`, leadDetailSchema);
export const fetchWorkspaces = () => bffGet("/bff/workspaces", workspaceSummariesSchema);
export const leadKey = (id: string) => ["lead", id] as const;
