import { api } from "./client";
import type { components } from "../../shared/api/schema";

export type Me = components["schemas"]["User"];

export const getMe = () => api<Me>("/api/me");
