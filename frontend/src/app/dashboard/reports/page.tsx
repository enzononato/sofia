"use client";

import { useState } from "react";
import { useReports } from "@/hooks/useReports";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";
import { BarChart3, Loader2, TrendingUp, Users, CalendarCheck, UserX } from "lucide-react";
import { cn } from "@/lib/utils";

const PIE_COLORS = ["#8b5cf6", "#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#ef4444"];
const RANGES = [7, 30, 90];

function shortDate(iso: string) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

function KpiCard({ icon: Icon, label, value, accent }: {
  icon: typeof Users; label: string; value: string; accent: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-5 shadow-xl flex items-center gap-4 hover:border-white/20 transition-all hover:-translate-y-0.5 duration-200">
      <div className={cn("flex h-11 w-11 items-center justify-center rounded-xl shrink-0 shadow-lg", accent)}>
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <p className="font-heading text-2xl font-bold tracking-tight text-foreground leading-none">{value}</p>
        <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground/70 mt-2">{label}</p>
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-background/45 backdrop-blur-md p-5 shadow-xl relative overflow-hidden">
      <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-muted-foreground/80 mb-4 border-b border-white/5 pb-2">{title}</h3>
      <div className="h-64">{children}</div>
    </div>
  );
}

const CUSTOM_TOOLTIP_STYLE = {
  backgroundColor: "rgba(17, 17, 17, 0.95)",
  borderColor: "rgba(255, 255, 255, 0.1)",
  borderRadius: "12px",
  padding: "10px 14px",
  boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5)",
};

export default function ReportsPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, isError } = useReports(days);

  return (
    <div className="flex flex-col h-full p-4 md:p-6 overflow-y-auto bg-background/5">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="font-heading text-2xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-primary" /> Relatórios
          </h1>
          <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">Visão geral da clínica nos últimos {days} dias.</p>
        </div>
        <div className="flex gap-1 bg-white/5 border border-white/10 rounded-full p-1 w-fit">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              className={cn(
                "text-[10px] px-3.5 py-1.5 rounded-full font-mono uppercase tracking-wider font-semibold transition-all duration-200 cursor-pointer",
                days === r ? "bg-primary text-primary-foreground shadow-md shadow-primary/20" : "text-muted-foreground hover:text-foreground hover:bg-white/5",
              )}
            >
              {r} dias
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>
      ) : isError || !data ? (
        <div className="p-4 border border-destructive/20 bg-destructive/5 text-destructive font-sans font-medium rounded-xl">
          Erro ao carregar relatórios. (Acesso restrito a administradores.)
        </div>
      ) : (
        <div className="space-y-6">
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard icon={TrendingUp} label="Taxa de conversão" value={`${Math.round(data.conversion_rate * 100)}%`} accent="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" />
            <KpiCard icon={Users} label="Novos leads" value={String(data.new_contacts)} accent="bg-blue-500/10 text-blue-400 border border-blue-500/20" />
            <KpiCard icon={CalendarCheck} label="Agendamentos futuros" value={String(data.upcoming_appointments)} accent="bg-amber-500/10 text-amber-400 border border-amber-500/20" />
            <KpiCard icon={UserX} label="Taxa de no-show" value={`${Math.round(data.no_show_rate * 100)}%`} accent="bg-red-500/10 text-red-400 border border-red-500/20" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartCard title="Tendência de leads">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.leads_trend.map((p) => ({ ...p, label: shortDate(p.date) }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" width={28} />
                  <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} itemStyle={{ color: "#fff", fontSize: 12 }} labelStyle={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }} />
                  <Line type="monotone" dataKey="count" name="Leads" stroke="#8b5cf6" strokeWidth={2.5} dot={{ stroke: "#8b5cf6", strokeWidth: 2, r: 2 }} activeDot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Distribuição por estágio (CRM)">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.stage_distribution.filter((s) => s.count > 0)}
                    dataKey="count" nameKey="label" cx="50%" cy="50%" outerRadius={80} label={{ fill: "#fff", fontSize: 10 }}
                  >
                    {data.stage_distribution.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="rgba(255,255,255,0.15)" strokeWidth={1} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} itemStyle={{ color: "#fff", fontSize: 12 }} labelStyle={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 10, color: "rgba(255,255,255,0.6)", paddingTop: 10 }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Agendamentos por status">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.appointments_by_status}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" width={28} />
                  <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} itemStyle={{ color: "#fff", fontSize: 12 }} labelStyle={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }} />
                  <Bar dataKey="count" name="Qtd." fill="#6366f1" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Volume de mensagens">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.messages_volume.map((p) => ({ ...p, label: shortDate(p.date) }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" width={28} />
                  <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} itemStyle={{ color: "#fff", fontSize: 12 }} labelStyle={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 10, color: "rgba(255,255,255,0.6)" }} />
                  <Line type="monotone" dataKey="inbound" name="Recebidas" stroke="#10b981" strokeWidth={2.5} dot={false} />
                  <Line type="monotone" dataKey="outbound" name="Enviadas" stroke="#3b82f6" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          {data.top_services.length > 0 && (
            <ChartCard title="Serviços mais agendados">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.top_services} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 10, fill: "rgba(255,255,255,0.5)" }} stroke="rgba(255,255,255,0.1)" width={120} />
                  <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} itemStyle={{ color: "#fff", fontSize: 12 }} labelStyle={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }} />
                  <Bar dataKey="count" name="Agendamentos" fill="#f59e0b" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          )}
        </div>
      )}
    </div>
  );
}
