import { api } from "../../shared/http/client";
import type { components } from "../../shared/api/schema";

export type Health = components["schemas"]["Health"];

export const getHealth = () => api<Health>("/healthz", false);
