import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";

export interface GoogleStatus {
  configured: boolean;
  connected: boolean;
  connected_at: string | null;
}

export function useGoogleStatus() {
  return useQuery({
    queryKey: ["google-status"],
    queryFn: async () => (await api.get<GoogleStatus>("/integrations/google/status")).data,
    staleTime: 60 * 1000,
    retry: false,
  });
}

export function useConnectGoogle() {
  return useMutation({
    mutationFn: async () =>
      (await api.get<{ authorization_url: string }>("/integrations/google/connect")).data,
    onSuccess: (data) => {
      window.location.href = data.authorization_url;
    },
  });
}

export function useDisconnectGoogle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => { await api.delete("/integrations/google"); },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["google-status"] }),
  });
}
