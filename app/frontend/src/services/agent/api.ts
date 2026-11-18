import type { components } from "../../shared/api/schema";
import { request } from "../api/client";

export type AgentMessageIn = components["schemas"]["AgentMessageIn"];
export type AgentResponse = components["schemas"]["AgentResponse"];

export const sendAgentMessage = (householdId: string, input: AgentMessageIn) =>
  request<AgentResponse>(
    `/api/households/${encodeURIComponent(householdId)}/agent/messages`,
    { method: "POST", body: JSON.stringify(input) },
  );
