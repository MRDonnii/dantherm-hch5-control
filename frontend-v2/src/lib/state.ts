export type HealthState = "idle" | "loading" | "ready" | "degraded" | "error";

export interface ResourceState<T> {
  status: HealthState;
  data: T | null;
  error: string | null;
  updatedAt: number | null;
}

type Listener = () => void;

export class Store<T> {
  private value: T;
  private readonly listeners = new Set<Listener>();

  constructor(initial: T) {
    this.value = initial;
  }

  getSnapshot = () => this.value;

  set(next: T | ((current: T) => T)) {
    this.value = typeof next === "function" ? (next as (current: T) => T)(this.value) : next;
    this.listeners.forEach(listener => listener());
  }

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}

export function emptyResource<T>(): ResourceState<T> {
  return { status: "idle", data: null, error: null, updatedAt: null };
}

// Separate resources are deliberate: one broken endpoint must never poison the
// rest of the application or its navigation.
export const liveStore = new Store<ResourceState<Record<string, unknown>>>(emptyResource());
export const controllerStore = new Store<ResourceState<Record<string, unknown>>>(emptyResource());
export const authStore = new Store<ResourceState<Record<string, unknown>>>(emptyResource());
export const historyStore = new Store<ResourceState<Record<string, unknown>>>(emptyResource());
