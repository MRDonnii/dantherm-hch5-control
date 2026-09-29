import { createContext, useContext } from "react";

export type Role = "admin" | "technician" | "user";
export type Permission = "control" | "configure" | "diagnostics" | "system" | "mail" | "users" | "login_switch";

export interface AuthStatus {
  configured?: boolean;
  enabled?: boolean;
  authenticated?: boolean;
  username?: string | null;
  csrf?: string | null;
  role?: Role | null;
  role_label?: string | null;
  permissions?: Permission[];
  email?: string | null;
  password_reset_available?: boolean;
}

export interface Session {
  auth: AuthStatus;
  /** True until the first /api/auth/status answer has arrived. */
  loading: boolean;
  can: (permission: Permission) => boolean;
  refresh: () => Promise<void>;
}

/**
 * Older gateways do not send permissions; they only know the single owner,
 * so an answer without a role is treated as full access.
 */
export function sessionCan(auth: AuthStatus, permission: Permission): boolean {
  if (!auth.role && !auth.permissions) return true;
  return (auth.permissions ?? []).includes(permission);
}

export const SessionContext = createContext<Session>({
  auth: {},
  loading: true,
  can: () => true,
  refresh: async () => {},
});

export function useSession(): Session {
  return useContext(SessionContext);
}

export const ROLE_NAMES: Record<Role, { da: string; en: string }> = {
  admin: { da: "Administrator", en: "Administrator" },
  technician: { da: "Tekniker", en: "Technician" },
  user: { da: "Bruger", en: "User" },
};
