import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getHousehold, getHouseholdContext, getRooms,
  type HouseholdView, type MeContext, type Membership, type RoomView,
} from "../../services/households/api";

type LoadState = "loading" | "ready" | "error";
type ContextLoad = { status: LoadState; value: MeContext | null };
type HouseLoad = { id: string; status: "ready" | "error"; house: HouseholdView | null; rooms: RoomView[] };

type HouseholdSession = {
  status: LoadState;
  membership: Membership | null;
  memberships: Membership[];
  residentName: string | null;
  selectedMembershipId: string | null;
  selectMembership: (id: string) => void;
  house: HouseholdView | null;
  rooms: RoomView[];
  houseStatus: "idle" | LoadState;
  reload: () => void;
};

const HouseholdContext = createContext<HouseholdSession | null>(null);

export const useHouseholdSession = (): HouseholdSession => {
  const context = useContext(HouseholdContext);
  if (!context) throw new Error("Falta HouseholdProvider");
  return context;
};

export function HouseholdProvider({ children }: { children: ReactNode }) {
  const [load, setLoad] = useState<ContextLoad>({ status: "loading", value: null });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [houseLoad, setHouseLoad] = useState<HouseLoad | null>(null);

  useEffect(() => {
    let active = true;
    getHouseholdContext()
      .then((value) => { if (active) setLoad({ status: "ready", value }); })
      .catch(() => { if (active) setLoad({ status: "error", value: null }); });
    return () => { active = false; };
  }, [reloadKey]);

  const memberships = useMemo(() => load.value?.memberships ?? [], [load.value]);
  const membership = memberships.find((item) => item.id === selectedId) ?? memberships[0] ?? null;
  const householdId = membership?.household_id ?? null;

  useEffect(() => {
    if (!householdId) return;
    let active = true;
    Promise.all([getHousehold(householdId), getRooms(householdId)])
      .then(([house, rooms]) => {
        if (active) setHouseLoad({ id: householdId, status: "ready", house, rooms });
      })
      .catch(() => {
        if (active) setHouseLoad({ id: householdId, status: "error", house: null, rooms: [] });
      });
    return () => { active = false; };
  }, [householdId, reloadKey]);

  // A seleção troca imediatamente o contexto de acesso; dados da casa anterior nunca aparecem.
  const matchingHouse = householdId && houseLoad?.id === householdId ? houseLoad : null;
  const value = useMemo<HouseholdSession>(() => ({
    status: load.status,
    membership,
    memberships,
    residentName: load.value?.resident?.display_name ?? null,
    selectedMembershipId: membership?.id ?? null,
    selectMembership: setSelectedId,
    house: matchingHouse?.house ?? null,
    rooms: matchingHouse?.rooms ?? [],
    houseStatus: !householdId ? "idle" : matchingHouse?.status ?? "loading",
    reload: () => {
      setLoad({ status: "loading", value: null });
      setHouseLoad(null);
      setReloadKey((key) => key + 1);
    },
  }), [load, membership, memberships, matchingHouse, householdId]);
  return <HouseholdContext.Provider value={value}>{children}</HouseholdContext.Provider>;
}
