import { mockService } from "../../mocks/home";
import { apiService } from "./api";

export const homeService = import.meta.env.VITE_OBJECTOS_SOURCE === "api" ? apiService : mockService;
