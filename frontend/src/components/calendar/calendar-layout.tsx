"use client";

import { useState, useMemo } from "react";
import { format, startOfDay, endOfDay, addDays, subDays, isToday, isSameDay, startOfWeek, addWeeks, subWeeks, eachDayOfInterval, getDay } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { useAppointments, useServices } from "@/hooks/useCalendar";
import { useContacts } from "@/hooks/useInbox";
import { DailyTimeline } from "./daily-timeline";
import { ChevronLeft, ChevronRight, CalendarDays, Clock, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export function CalendarLayout() {
  const [date, setDate] = useState<Date>(new Date());

  const dateFrom = startOfDay(date).toISOString();
  const dateTo = endOfDay(date).toISOString();

  // Fetch data
  const { data: appointments, isLoading: isLoadingAppts } = useAppointments(dateFrom, dateTo);
  const { data: contacts, isLoading: isLoadingContacts } = useContacts();
  const { data: services, isLoading: isLoadingServices } = useServices();

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
    <div className="flex h-[calc(100vh-60px)] w-full overflow-hidden bg-background">
      {/* ── Left Sidebar ── */}
      <div className="hidden lg:flex flex-col w-[340px] border-r border-border/50 flex-shrink-0 bg-card/30 backdrop-blur-md overflow-y-auto">
        {/* Custom Calendar */}
        <div className="p-5">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-xl font-bold tracking-tight">Agenda</h2>
            <Button variant="outline" size="sm" onClick={goToday} className="text-xs h-7 rounded-full px-3 border-border/50">
              Hoje
            </Button>
          </div>

          <div className="rounded-2xl border border-border/50 bg-card p-4 shadow-md">
            {/* Month Header */}
            <div className="flex items-center justify-between mb-4">
              <Button variant="ghost" size="icon" onClick={goPrevMonth} className="h-8 w-8 rounded-full">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm font-semibold capitalize">
                {format(date, "MMMM yyyy", { locale: ptBR })}
              </span>
              <Button variant="ghost" size="icon" onClick={goNextMonth} className="h-8 w-8 rounded-full">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>

            {/* Weekday Labels */}
            <div className="grid grid-cols-7 mb-2">
              {weekDayLabels.map(d => (
                <div key={d} className="text-center text-[10px] font-medium text-muted-foreground uppercase tracking-wider py-1">
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
                      "relative mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm transition-all duration-200",
                      !isCurrentMonth && "text-muted-foreground/30",
                      isCurrentMonth && !isSelected && "text-foreground hover:bg-muted",
                      isTodayDay && !isSelected && "ring-1 ring-primary/40 text-primary font-semibold",
                      isSelected && "bg-primary text-primary-foreground font-semibold shadow-lg shadow-primary/25 scale-110",
                    )}
                  >
                    {format(day, "d")}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="px-5 pb-5 space-y-3">
          <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2">
            Resumo do dia
          </h3>

          <div className="grid grid-cols-1 gap-3">
            <div className="flex items-center gap-3 rounded-xl border border-border/50 bg-card p-3 shadow-sm">
              <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-primary/10 text-primary">
                <CalendarDays className="h-4 w-4" />
              </div>
              <div>
                <p className="text-2xl font-bold leading-none">{totalAppts}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">Agendamentos</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col items-center rounded-xl border border-border/50 bg-card p-3 shadow-sm">
                <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-emerald-500/10 text-emerald-500 mb-1">
                  <CheckCircle2 className="h-4 w-4" />
                </div>
                <p className="text-lg font-bold leading-none">{confirmed}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">Ativos</p>
              </div>

              <div className="flex flex-col items-center rounded-xl border border-border/50 bg-card p-3 shadow-sm">
                <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-destructive/10 text-destructive mb-1">
                  <XCircle className="h-4 w-4" />
                </div>
                <p className="text-lg font-bold leading-none">{cancelled}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">Cancelados</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Main Content: Daily Timeline ── */}
      <div className="flex-1 flex flex-col min-w-0 bg-background relative overflow-hidden">
        {/* Day Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 bg-card/60 backdrop-blur-md sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => setDate(subDays(date, 1))} className="h-8 w-8 rounded-full">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div>
              <h2 className="text-lg font-bold capitalize">
                {format(date, "EEEE", { locale: ptBR })}
              </h2>
              <p className="text-xs text-muted-foreground">
                {format(date, "d 'de' MMMM 'de' yyyy", { locale: ptBR })}
              </p>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setDate(addDays(date, 1))} className="h-8 w-8 rounded-full">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          <div className="flex items-center gap-2">
            {isToday(date) ? (
              <span className="text-xs font-medium bg-primary/10 text-primary px-3 py-1 rounded-full ring-1 ring-primary/20">
                Hoje
              </span>
            ) : (
              <Button variant="outline" size="sm" onClick={goToday} className="text-xs h-7 rounded-full px-3 border-border/50">
                Ir para Hoje
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          <DailyTimeline
            date={date}
            appointments={appointments || []}
            contacts={contacts || []}
            services={services || []}
            isLoading={isLoading}
          />
        </div>
      </div>
    </div>
  );
}
