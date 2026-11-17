import type { components, paths } from "../../shared/api/schema";
import { api } from "../api/client";

export type CameraStatus = components["schemas"]["CameraStatus"];
export type McpTool = paths["/api/mcp/tools"]["get"]["responses"]["200"]["content"]["application/json"][number];

export const listMcpTools = () => api<McpTool[]>("/api/mcp/tools");
export const getCameraStatus = () => api<CameraStatus>("/api/presence/camera/status");
