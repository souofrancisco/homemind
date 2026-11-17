import type { components } from "../shared/api/schema";

// Tipos vindos do OpenAPI do backend (`make contracts`). Não redefinir à mão.
type Schemas = components["schemas"];
export type ScenarioId = "book" | "remote" | "mug" | "absence" | "return";

export interface HomeService {
  /** "api" = backend real (FakeHome ou MCP); "mock" = só fallback de desenvolvimento no browser. */
  mode: "mock" | "api";
  connect(onState: (state: HomeState) => void, onEvent: (event: EventLogItem) => void, onStatus: (online: boolean) => void): () => void;
  getState(): Promise<HomeState>;
  getEvents(): Promise<EventLogItem[]>;
  simulate(scenario: ScenarioId): Promise<void>;
  getRules(): Promise<HomeRule[]>;
  setRuleEnabled(id: string, enabled: boolean): Promise<HomeRule>;
  deleteRule(id: string): Promise<void>;
  proposeRule(text: string): Promise<RuleProposal>;
  saveRule(rule: RuleDraft): Promise<HomeRule>;
  turnOff(): Promise<OffResult>;
}

export type HomeMode = string | null;
export type HomeStatus = Schemas["HomeState"]["state"];
export type DataSource = Schemas["HomeState"]["backend"];

export type HomeState = Schemas["HomeState"];
export type CasaState = Schemas["EstadoCasa"];

// Só id/timestamp/level/message/source vêm do backend. Os campos extra são opcionais e só os traz o mock.
export type EventLogItem = Schemas["EventLogItem"] & {
  category?: EventCategory;
  correlation_id?: string;
  details?: Record<string, unknown>;
  result?: "verified" | "failed" | "unverified" | "unsupported";
};

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

export type RuleAction = Schemas["AcaoLampada"] | Schemas["AcaoTomada"];
export type HomeRule = Schemas["Rule"];
export type RuleDraft = Omit<HomeRule, "enabled">;
export type RuleProposal = Omit<Schemas["ParseResponse"], "proposal"> & { proposal: RuleDraft };
export type OffResult = Schemas["OffResult"];

/** Eventos da mesma operação (correlation_id) agrupados; `newest` = timestamp do mais recente. */
export interface EventGroup { events: EventLogItem[]; newest: number }
