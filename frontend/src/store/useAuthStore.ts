import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { jwtDecode } from 'jwt-decode';
import api from '@/lib/axios';

export interface TenantRead {
  id: string;
  name: string;
  slug: string;
  plan: string;
  is_active: boolean;
  ai_config: {
    model: string;
    system_prompt: string;
    temperature: number;
    max_output_tokens?: number;
    multimodal_enabled?: boolean;
  };
  settings: {
    whatsapp?: {
      // Secrets (webhook_secret, provider keys) are never sent to the client.
      instance?: string;
      status?: string;
    };
    schedule?: {
      timezone?: string;
      working_days?: number[];
      open_time?: string;
      close_time?: string;
      lunch_start?: string;
      lunch_end?: string;
      slot_granularity_minutes?: number;
    };
  };
}

interface JwtPayload {
  sub: string;
  tenant_id: string;
  role: 'owner' | 'admin' | 'receptionist' | 'professional' | 'viewer';
  email: string;
  exp: number;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  tenantId: string | null;
  userId: string | null;
  userRole: 'owner' | 'admin' | 'receptionist' | 'professional' | 'viewer' | null;
  userEmail: string | null;
  tenant: TenantRead | null;
  // True once zustand/persist has finished reading auth-storage from
  // localStorage. Consumers (e.g. dashboard/layout.tsx) must wait for this
  // before treating a null accessToken as "logged out" — otherwise a hard
  // page reload briefly reads the pre-hydration default and redirects to
  // /login even though a valid session is sitting in storage.
  _hasHydrated: boolean;
}

interface AuthActions {
  login: (accessToken: string, refreshToken: string) => Promise<void>;
  logout: () => Promise<void>;
  fetchTenant: () => Promise<void>;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setHasHydrated: (hasHydrated: boolean) => void;
}

export const useAuthStore = create<AuthState & AuthActions>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      tenantId: null,
      userId: null,
      userRole: null,
      userEmail: null,
      tenant: null,
      _hasHydrated: false,

      setTokens: (accessToken: string, refreshToken: string) => {
        set({ accessToken, refreshToken });
      },

      setHasHydrated: (hasHydrated: boolean) => {
        set({ _hasHydrated: hasHydrated });
      },

      login: async (accessToken: string, refreshToken: string) => {
        try {
          const decoded = jwtDecode<JwtPayload>(accessToken);

          set({
            accessToken,
            refreshToken,
            tenantId: decoded.tenant_id,
            userId: decoded.sub,
            userRole: decoded.role,
            userEmail: decoded.email,
          });

          // Fire and forget — dashboard layout will await the result if needed
          get().fetchTenant();
        } catch (error) {
          console.error('Failed to decode token during login', error);
          get().logout();
        }
      },

      fetchTenant: async () => {
        try {
          // Since interceptor uses get().accessToken, this request will have the auth headers
          const response = await api.get('/tenants/me');
          set({ tenant: response.data });
        } catch (error) {
          console.error('Failed to fetch tenant', error);
        }
      },

      logout: async () => {
        const { refreshToken } = get();
        if (refreshToken) {
          try {
            await api.post('/auth/logout', { refresh_token: refreshToken });
          } catch (error) {
            console.error('Failed to logout on backend', error);
          }
        }
        
        set({
          accessToken: null,
          refreshToken: null,
          tenantId: null,
          userId: null,
          userRole: null,
          userEmail: null,
          tenant: null,
        });
      },
    }),
    {
      name: 'auth-storage',
      // Only persist the token and basic info, not the full tenant object which can change
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        tenantId: state.tenantId,
        userId: state.userId,
        userRole: state.userRole,
        userEmail: state.userEmail
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);
