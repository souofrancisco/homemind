import { mockService } from "../../mocks/home";
import { apiService } from "./api";

// Backend real por omissão (FakeHome ou MCP). O mock do browser só com VITE_OBJECTOS_SOURCE=mock.
export const homeService = import.meta.env.VITE_OBJECTOS_SOURCE === "mock" ? mockService : apiService;
