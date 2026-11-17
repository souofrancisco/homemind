export interface HomeService {
  mode: "mock" | "api";
  connect(onState: (state: HomeState) => void, onEvent: (event: EventLogItem) => void, onStatus: (online: boolean) => void): () => void;
  getEvents(): Promise<EventLogItem[]>;
  getRules(): Promise<HomeRule[]>;
  setRuleEnabled(id: string, enabled: boolean): Promise<HomeRule>;
  deleteRule(id: string): Promise<void>;
  proposeRule(text: string): Promise<RuleProposal>;
  saveRule(rule: RuleDraft): Promise<HomeRule>;
  turnOff(): Promise<OffResult>;
}

export type HomeMode = string | null;
export type HomeStatus = "ativo" | "em_espera" | "suspenso" | "inativo";
export type DataSource = "fake" | "mcp";

export interface HomeState {
  mode: HomeMode;
  mode_name?: string | null;
  state: HomeStatus;
  presence: boolean | null;
  camera_ok: boolean;
  mcp_ok: boolean;
  backend: DataSource;
  waiting_remaining_seconds: number | null;
  energy_saved_wh: number;
  energy_saved_eur: number;
  updated_at: string;
  casa?: CasaState | null;
}

export interface CasaState {
  backend: DataSource;
  mcp_ok: boolean;
  lampada?: { ligada: boolean; cor: string | null; rgb: number[] | null; brilho: number | null } | null;
  tomada?: { ligada: boolean; consumo_w: number | null; consumo_lido_em: string | null } | null;
  atualizado_em: string;
  aviso: string | null;
}

export interface EventLogItem {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
  source: DataSource;
  category?: EventCategory;
  correlation_id?: string;
  details?: Record<string, unknown>;
  result?: "verified" | "failed" | "unverified" | "unsupported";
}

export type EventCategory = "presence" | "object" | "gesture" | "mode" | "rule" | "device" | "energy" | "system";

export interface ObservedEvent { id: string; occurredAt: string; text: string; source: DataSource }
export interface InferredPattern {
  id: string;
  statement: string;
  frequency: string;
  timeWindow: string;
  evidence: string[];
  simulated: true;
}
export interface ConfirmedPreference { id: string; statement: string; confirmedAt: string }
export interface MemorySnapshot {
  profileId: string;
  updatedAt: string;
  learningEnabled: boolean;
  observedEvents: ObservedEvent[];
  inferredPatterns: InferredPattern[];
  confirmedPreferences: ConfirmedPreference[];
  pendingSuggestions: string[];
  ignoredSuggestions: string[];
}
export interface RoutineSuggestion extends InferredPattern {
  title: string;
  explanation: string;
  proposedRule: RuleDraft;
}

export interface RuleAction { dispositivo: string; ligada: boolean; cor?: string; brilho?: number }
export interface HomeRule { id: string; objeto: string; nome: string; enabled: boolean; acoes: RuleAction[] }
export type RuleDraft = Omit<HomeRule, "enabled">;
export interface RuleProposal { proposal: RuleDraft; summary: string }
export interface OffResult { success: boolean; state: HomeStatus; backend: DataSource; message: string }

/** Eventos da mesma operação (correlation_id) agrupados; `newest` = timestamp do mais recente. */
export interface EventGroup { events: EventLogItem[]; newest: number }
