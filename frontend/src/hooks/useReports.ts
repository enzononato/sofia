import { useQuery } from "@tanstack/react-query";
import api from "@/lib/axios";

export interface TrendPoint { date: string; count: number; }
export interface NamedCount { label: string; count: number; }
export interface MessageVolumePoint { date: string; inbound: number; outbound: number; }

export interface ReportOverview {
  days: number;
  total_contacts: number;
  new_contacts: number;
  converted_contacts: number;
  conversion_rate: number;
  total_appointments: number;
  upcoming_appointments: number;
  no_show_rate: number;
  leads_trend: TrendPoint[];
  stage_distribution: NamedCount[];
  appointments_by_status: NamedCount[];
  top_services: NamedCount[];
  messages_volume: MessageVolumePoint[];
}

export function useReports(days = 30) {
  return useQuery({
    queryKey: ["reports", days],
    queryFn: async () => {
      const res = await api.get<ReportOverview>("/reports/overview", { params: { days } });
      return res.data;
    },
    staleTime: 60 * 1000,
  });
}
