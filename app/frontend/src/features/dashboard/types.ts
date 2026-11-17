export type HomeMode = "leitura" | "cinema" | "cafe" | null;
export type HomeStatus = "ativo" | "em_espera" | "suspenso" | "inativo";
export type DataSource = "fake" | "mcp";

export interface HomeState {
  mode: HomeMode;
  state: HomeStatus;
  presence: boolean;
  camera_ok: boolean;
  mcp_ok: boolean;
  backend: DataSource;
  waiting_remaining_seconds: number | null;
  energy_saved_wh: number;
  energy_saved_eur: number;
  updated_at: string;
}

export interface EventLogItem {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
  source: DataSource;
}

export interface RuleAction { dispositivo: string; ligada: boolean; cor?: string; brilho?: number }
export interface HomeRule { id: string; objeto: string; nome: string; enabled: boolean; acoes: RuleAction[] }
export type RuleDraft = Omit<HomeRule, "enabled">;
export interface RuleProposal { proposal: RuleDraft; summary: string }
export interface OffResult { success: boolean; state: HomeStatus; backend: DataSource; message: string }
