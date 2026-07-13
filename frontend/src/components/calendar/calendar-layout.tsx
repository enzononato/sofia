"use client";

import { useState, useMemo } from "react";
import { format, startOfDay, endOfDay, addDays, subDays, isToday, isSameDay, startOfWeek, addWeeks, subWeeks, eachDayOfInterval, getDay } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { useAppointments, useServices, type Appointment } from "@/hooks/useCalendar";
import { useContacts } from "@/hooks/useInbox";
import { useTeamMembers } from "@/hooks/useTeam";
import { DailyTimeline } from "./daily-timeline";
import { AppointmentModal } from "./appointment-modal";
import { GoogleCalendarButton } from "./google-calendar-button";
import { ChevronLeft, ChevronRight, CalendarDays, CheckCircle2, XCircle, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

export function CalendarLayout() {
  const [date, setDate] = useState<Date>(new Date());
  const [modalOpen, setModalOpen] = useState(false);
  const [editingAppt, setEditingAppt] = useState<Appointment | null>(null);
  const [selectedProfessionalId, setSelectedProfessionalId] = useState<string>("");

  const openNew = () => { setEditingAppt(null); setModalOpen(true); };
  const openEdit = (appt: Appointment) => { setEditingAppt(appt); setModalOpen(true); };

  const dateFrom = startOfDay(date).toISOString();
  const dateTo = endOfDay(date).toISOString();

  // Fetch data
  const { data: appointments, isLoading: isLoadingAppts } = useAppointments(dateFrom, dateTo, selectedProfessionalId || undefined);
  const { data: contacts, isLoading: isLoadingContacts } = useContacts();
  const { data: services, isLoading: isLoadingServices } = useServices();
  const { data: team, isLoading: isLoadingTeam } = useTeamMembers();

  // Anyone active can be linked to an appointment as `professional_id` (the
  // backend only checks tenant membership, not role — see
  // `_assert_user_belongs_to_tenant` in app/api/v1/routes/appointments.py), so
  // this mirrors the exact same filter already used in appointment-modal.tsx's
  // `attendingTeam` for the professional picker in the create/edit form.
  const attendingTeam = (team || []).filter((u) => u.is_active);

  const isLoading = isLoadingAppts || isLoadingContacts || isLoadingServices;

  // Build the custom calendar grid
  const calendarWeeks = useMemo(() => {
    const monthStart = new Date(date.getFullYear(), date.getMonth(), 1);
    const monthEnd = new Date(date.getFullYear(), date.getMonth() + 1, 0);
    const calStart = startOfWeek(monthStart, { locale: ptBR });
    const calEnd = addDays(startOfWeek(addDays(monthEnd, 6), { locale: ptBR }), 6);

    const days = eachDayOfInterval({ start: calStart, end: calEnd });
    const weeks: Date[][] = [];
    for (let i = 0; i < days.length; i += 7) {
      weeks.push(days.slice(i, i + 7));
    }
    return weeks;
  }, [date]);

  const goToday = () => setDate(new Date());
  const goPrevMonth = () => setDate(new Date(date.getFullYear(), date.getMonth() - 1, 1));
  const goNextMonth = () => setDate(new Date(date.getFullYear(), date.getMonth() + 1, 1));

  const totalAppts = appointments?.length || 0;
  const confirmed = appointments?.filter(a => a.status === "confirmed" || a.status === "scheduled").length || 0;
  const cancelled = appointments?.filter(a => a.status === "cancelled").length || 0;

  const weekDayLabels = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

  return (
    <div className="flex h-[calc(100vh-64px)] w-full overflow-hidden bg-background">
      {/* ── Left Sidebar ── */}
      <div className="hidden lg:flex flex-col w-[340px] border-r border-white/10 flex-shrink-0 bg-background/15 backdrop-blur-md overflow-y-auto">
        {/* Custom Calendar */}
        <div className="p-5">
          <div className="flex items-center justify-between mb-5">
            <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">Agenda</h2>
            <Button variant="outline" size="sm" onClick={goToday} className="text-xs h-7 rounded-full px-3 border-white/10 bg-white/5 hover:bg-white/10 cursor-pointer">
              Hoje
            </Button>
          </div>

          <div className="rounded-2xl border border-white/10 bg-background/45 backdrop-blur-md p-4 shadow-xl">
            {/* Month Header */}
            <div className="flex items-center justify-between mb-4">
              <Button variant="ghost" size="icon" onClick={goPrevMonth} className="h-8 w-8 rounded-full cursor-pointer hover:bg-white/5">
                <ChevronLeft className="h-4 w-4 text-muted-foreground" />
              </Button>
              <span className="font-heading text-sm font-semibold capitalize text-foreground">
                {format(date, "MMMM yyyy", { locale: ptBR })}
              </span>
              <Button variant="ghost" size="icon" onClick={goNextMonth} className="h-8 w-8 rounded-full cursor-pointer hover:bg-white/5">
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              </Button>
            </div>

            {/* Weekday Labels */}
            <div className="grid grid-cols-7 mb-2">
              {weekDayLabels.map(d => (
                <div key={d} className="text-center text-[10px] font-mono text-muted-foreground/60 uppercase tracking-wider py-1">
                  {d}
                </div>
              ))}
            </div>

            {/* Days Grid */}
            <div className="grid grid-cols-7 gap-y-1">
              {calendarWeeks.flat().map((day, idx) => {
                const isCurrentMonth = day.getMonth() === date.getMonth();
                const isSelected = isSameDay(day, date);
                const isTodayDay = isToday(day);

                return (
                  <button
                    key={idx}
                    onClick={() => setDate(day)}
                    className={cn(
                      "relative mx-auto flex h-9 w-9 items-center justify-center rounded-full text-xs transition-all duration-200 cursor-pointer",
                      !isCurrentMonth && "text-muted-foreground/20",
                      isCurrentMonth && !isSelected && "text-foreground/90 hover:bg-white/5",
                      isTodayDay && !isSelected && "ring-1 ring-primary/40 text-primary font-semibold",
                      isSelected && "bg-primary text-primary-foreground font-semibold shadow-lg shadow-primary/25 scale-105",
                    )}
                  >
                    {format(day, "d")}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Day Summary — three stacked rows (matches Stitch mockup) */}
        <div className="px-5 pb-5">
          <div className="mb-4">
            <p className="font-mono text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
              Resumo do dia
            </p>
            <h3 className="font-heading text-base font-semibold capitalize text-foreground mt-0.5">
              {isToday(date) ? "Hoje, " : ""}{format(date, "d 'de' MMMM", { locale: ptBR })}
            </h3>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-4 shadow-md">
              <span className="flex items-center gap-2.5 text-sm text-muted-foreground">
                <CalendarDays className="h-4 w-4 text-muted-foreground/70" />
                Agendamentos
              </span>
              <span className="rounded-md bg-primary/20 px-2.5 py-0.5 font-mono text-sm font-semibold text-primary">
                {String(totalAppts).padStart(2, "0")}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-4 shadow-md">
              <span className="flex items-center gap-2.5 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-400/80" />
                Confirmados
              </span>
              <span className="rounded-md bg-emerald-500/20 px-2.5 py-0.5 font-mono text-sm font-semibold text-emerald-400">
                {String(confirmed).padStart(2, "0")}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-4 shadow-md">
              <span className="flex items-center gap-2.5 text-sm text-muted-foreground">
                <XCircle className="h-4 w-4 text-destructive/80" />
                Cancelados
              </span>
              <span className="rounded-md bg-destructive/20 px-2.5 py-0.5 font-mono text-sm font-semibold text-destructive">
                {String(cancelled).padStart(2, "0")}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Main Content: Daily Timeline ── */}
      <div className="flex-1 flex flex-col min-w-0 bg-background relative overflow-hidden">
        {/* Day Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-background/45 backdrop-blur-md sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => setDate(subDays(date, 1))} className="h-8 w-8 rounded-full cursor-pointer hover:bg-white/5">
              <ChevronLeft className="h-4 w-4 text-muted-foreground" />
            </Button>
            <div>
              <h2 className="font-heading text-lg font-bold capitalize text-foreground">
                {format(date, "EEEE", { locale: ptBR })}
              </h2>
              <p className="text-xs text-muted-foreground opacity-80 mt-0.5">
                {format(date, "d 'de' MMMM 'de' yyyy", { locale: ptBR })}
              </p>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setDate(addDays(date, 1))} className="h-8 w-8 rounded-full cursor-pointer hover:bg-white/5">
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </Button>
          </div>

          <div className="flex items-center gap-2">
            {isToday(date) ? (
              <span className="text-xs font-semibold bg-primary/10 text-primary px-3 py-1 rounded-full ring-1 ring-primary/20">
                Hoje
              </span>
            ) : (
              <Button variant="outline" size="sm" onClick={goToday} className="text-xs h-7 rounded-full px-3 border-white/10 bg-white/5 hover:bg-white/10 cursor-pointer">
                Ir para Hoje
              </Button>
            )}
            <select
              aria-label="Filtrar por profissional"
              value={selectedProfessionalId}
              onChange={(e) => setSelectedProfessionalId(e.target.value)}
              disabled={isLoadingTeam}
              className="h-8 rounded-full px-3 text-xs border border-white/10 bg-white/5 hover:bg-white/10 text-foreground disabled:opacity-50 cursor-pointer appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_0.5rem_center] bg-[length:1rem] pr-7"
            >
              <option value="" className="bg-background">Todos os profissionais</option>
              {attendingTeam.map((u) => (
                <option key={u.id} value={u.id} className="bg-background">{u.full_name}</option>
              ))}
            </select>
            <GoogleCalendarButton />
            <Button size="sm" onClick={openNew} className="h-8 rounded-full px-4 cursor-pointer bg-primary text-primary-foreground hover:brightness-110 transition-all font-semibold text-xs shadow-md shadow-primary/20">
              <Plus className="mr-1.5 h-4 w-4" /> Novo agendamento
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          <DailyTimeline
            date={date}
            appointments={appointments || []}
            contacts={contacts || []}
            services={services || []}
            isLoading={isLoading}
            onSelect={openEdit}
            professionalId={selectedProfessionalId || undefined}
          />
        </div>
      </div>

      <AppointmentModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        appointment={editingAppt}
        defaultDate={date}
      />
    </div>
  );
}
