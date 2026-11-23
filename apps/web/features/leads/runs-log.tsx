import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import {
  formatCost,
  formatLatency,
  formatTokens,
  runsSummary,
  runTotals,
} from "@/lib/leads/review";
import { fetchRuns, runsKey } from "./queries";

/** Collapsed log of the agent's model calls, one table per run. */
export function RunsLog({ leadId }: { leadId: string }) {
  const query = useQuery({ queryKey: runsKey(leadId), queryFn: () => fetchRuns(leadId) });
  if (query.isError)
    return (
      <p className="muted" role="status">
        The agent run log could not be loaded: {query.error.message}
      </p>
    );
  const runs = query.data?.filter((run) => run.calls.length > 0);
  if (!runs?.length) return null;
  return (
    <details className="log" id="runlog">
      <summary>
        <ChevronDown className="ic chev" aria-hidden="true" />
        Agent run log <span className="muted">{runsSummary(runs)}</span>
      </summary>
      {runs.map((run) => {
        const totals = runTotals(run);
        return (
          <table className="runlog" key={run.id}>
            <caption className="sr">
              Agent run {run.run_number}: one row per model call
            </caption>
            <thead>
              <tr>
                <th scope="col">Node</th>
                <th scope="col">Provider and model</th>
                <th scope="col">Prompt</th>
                <th scope="col" className="r">
                  Tokens in
                </th>
                <th scope="col" className="r">
                  Tokens out
                </th>
                <th scope="col" className="r">
                  Latency
                </th>
                <th scope="col" className="r">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody>
              {run.calls.map((call) => (
                <tr key={call.id}>
                  <th scope="row" data-label="Node">
                    {call.node}
                    {call.attempt > 1 ? ` (attempt ${call.attempt})` : ""}
                    {call.success ? "" : ` failed: ${call.error_code ?? "error"}`}
                  </th>
                  <td data-label="Model">
                    {call.provider} / {call.model}
                  </td>
                  <td data-label="Prompt">{call.prompt_version ?? "n/a"}</td>
                  <td className="num r" data-label="Tokens in">
                    {formatTokens(call.input_tokens)}
                  </td>
                  <td className="num r" data-label="Tokens out">
                    {formatTokens(call.output_tokens)}
                  </td>
                  <td className="num r" data-label="Latency">
                    {formatLatency(call.latency_ms)}
                  </td>
                  <td className="num r" data-label="Cost">
                    {formatCost(call.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="total">
                <th scope="row" data-label="Run">
                  Run #{run.run_number} total
                </th>
                <td data-label="Status">{run.status}</td>
                <td data-label="Graph">{run.graph_version}</td>
                <td className="num r" data-label="Tokens in">
                  {formatTokens(totals.input)}
                </td>
                <td className="num r" data-label="Tokens out">
                  {formatTokens(totals.output)}
                </td>
                <td className="num r" data-label="Latency">
                  {formatLatency(totals.latencyMs)}
                </td>
                <td className="num r" data-label="Cost">
                  {formatCost(run.total_cost_usd)}
                </td>
              </tr>
            </tfoot>
          </table>
        );
      })}
    </details>
  );
}
