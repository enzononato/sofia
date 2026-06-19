"use client";

import { useState } from "react";
import { useReports } from "@/hooks/useReports";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import { BarChart3, Loader2, TrendingUp, Users, CalendarCheck, UserX } from "lucide-react";
import { cn } from "@/lib/utils";

const PIE_COLORS = ["#94a3b8", "#60a5fa", "#fbbf24", "#34d399", "#a78bfa", "#f87171"];
const RANGES = [7, 30, 90];

function shortDate(iso: string) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

function KpiCard({ icon: Icon, label, value, accent }: {
  icon: typeof Users; label: string; value: string; accent: string;
}) {
  return (
    <div className="rounded-xl border border-border/50 bg-card p-4 shadow-sm flex items-center gap-3">
      <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg", accent)}>
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <p className="text-2xl font-bold leading-none">{value}</p>
        <p className="text-xs text-muted-foreground mt-1">{label}</p>
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border/50 bg-card p-4 shadow-sm">
      <h3 className="text-sm font-semibold mb-3">{title}</h3>
      <div className="h-64">{children}</div>
    </div>
  );
}

export default function ReportsPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, isError } = useReports(days);

  return (
    <div className="flex flex-col h-full p-4 md:p-6 overflow-y-auto">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-primary" /> Relatórios
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">Visão geral da clínica nos últimos {days} dias.</p>
        </div>
        <div className="flex gap-1 bg-muted rounded-full p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              className={cn(
                "text-xs px-3 py-1.5 rounded-full font-medium transition-colors",
                days === r ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {r} dias
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
      ) : isError || !data ? (
        <div className="p-4 border border-destructive/50 bg-destructive/5 text-destructive rounded-lg">
          Erro ao carregar relatórios. (Acesso restrito a administradores.)
        </div>
      ) : (
        <div className="space-y-6">
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard icon={TrendingUp} label="Taxa de conversão" value={`${Math.round(data.conversion_rate * 100)}%`} accent="bg-emerald-500/10 text-emerald-600" />
            <KpiCard icon={Users} label="Novos leads" value={String(data.new_contacts)} accent="bg-blue-500/10 text-blue-600" />
            <KpiCard icon={CalendarCheck} label="Agendamentos futuros" value={String(data.upcoming_appointments)} accent="bg-amber-500/10 text-amber-600" />
            <KpiCard icon={UserX} label="Taxa de no-show" value={`${Math.round(data.no_show_rate * 100)}%`} accent="bg-red-500/10 text-red-600" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartCard title="Tendência de leads">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.leads_trend.map((p) => ({ ...p, label: shortDate(p.date) }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
                  <Tooltip />
                  <Line type="monotone" dataKey="count" name="Leads" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Distribuição por estágio (CRM)">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.stage_distribution.filter((s) => s.count > 0)}
                    dataKey="count" nameKey="label" cx="50%" cy="50%" outerRadius={80} label
                  >
                    {data.stage_distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Agendamentos por status">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.appointments_by_status}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
                  <Tooltip />
                  <Bar dataKey="count" name="Qtd." fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Volume de mensagens">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.messages_volume.map((p) => ({ ...p, label: shortDate(p.date) }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="inbound" name="Recebidas" stroke="#10b981" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="outbound" name="Enviadas" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          {data.top_services.length > 0 && (
            <ChartCard title="Serviços mais agendados">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.top_services} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 11 }} width={120} />
                  <Tooltip />
                  <Bar dataKey="count" name="Agendamentos" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          )}
        </div>
      )}
    </div>
  );
}
