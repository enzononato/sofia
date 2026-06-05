"use client";

import { useMemo } from "react";
import { format, differenceInMinutes, startOfDay, addHours, isToday } from "date-fns";
import { Appointment, Service } from "@/hooks/useCalendar";
import { Contact } from "@/hooks/useInbox";
import { cn } from "@/lib/utils";
import { Clock, User, CalendarOff } from "lucide-react";

interface DailyTimelineProps {
  date: Date;
  appointments: Appointment[];
  contacts: Contact[];
  services: Service[];
  isLoading: boolean;
}

const START_HOUR = 7;
const END_HOUR = 19;
const ROW_HEIGHT = 72; // pixels per hour

export function DailyTimeline({ date, appointments, contacts, services, isLoading }: DailyTimelineProps) {
  const hours = useMemo(() => {
    const arr = [];
    const baseDate = startOfDay(date);
    for (let i = START_HOUR; i <= END_HOUR; i++) {
      arr.push(addHours(baseDate, i));
    }
    return arr;
  }, [date]);

  // Current-time indicator position (only when viewing today)
  const nowIndicator = useMemo(() => {
    if (!isToday(date)) return null;
    const now = new Date();
    const minsFromStart = differenceInMinutes(now, addHours(startOfDay(date), START_HOUR));
    if (minsFromStart < 0 || minsFromStart > (END_HOUR - START_HOUR) * 60) return null;
    return (minsFromStart / 60) * ROW_HEIGHT;
  }, [date]);

  const enrichedAppointments = useMemo(() => {
    return appointments.map((appt) => {
      const scheduledAt = new Date(appt.scheduled_at);

      let durationMins = 30;
      if (appt.ends_at) {
        durationMins = differenceInMinutes(new Date(appt.ends_at), scheduledAt);
      } else if (appt.service_id) {
        const svc = services.find(s => s.id === appt.service_id);
        if (svc) durationMins = svc.duration_minutes;
      }

      const minsFromStart = differenceInMinutes(scheduledAt, addHours(startOfDay(date), START_HOUR));
      const topPos = (minsFromStart / 60) * ROW_HEIGHT;
      const height = (durationMins / 60) * ROW_HEIGHT;

      const contact = contacts.find(c => c.id === appt.contact_id);
      const service = services.find(s => s.id === appt.service_id);

      return {
        ...appt,
        contactName: contact?.full_name || "Paciente",
        serviceName: service?.name || "Consulta",
        topPos,
        height: Math.max(height, 36),
        scheduledAt,
        durationMins,
      };
    });
  }, [appointments, contacts, services, date]);

  if (isLoading) {
    return (
      <div className="p-6 space-y-3 animate-pulse">
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="flex gap-4 items-start">
            <div className="w-14 h-4 bg-muted rounded mt-1 shrink-0"></div>
            <div className="flex-1 h-14 bg-muted/40 rounded-xl border border-border/30"></div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="relative min-h-full p-4 lg:px-8 lg:py-6">
      <div className="relative rounded-2xl border border-border/40 bg-card/20 shadow-sm overflow-hidden">

        {/* Hour rows */}
        <div className="relative">
          {hours.map((hour, idx) => (
            <div
              key={hour.toISOString()}
              className={cn(
                "flex items-start",
                idx !== hours.length - 1 && "border-b border-border/30"
              )}
              style={{ height: ROW_HEIGHT }}
            >
              {/* Hour label */}
              <div className="w-16 lg:w-20 pr-3 pt-1.5 text-right text-[11px] font-medium text-muted-foreground/70 border-r border-border/30 h-full select-none">
                {format(hour, "HH:mm")}
              </div>
              {/* Slot area */}
              <div className="flex-1 relative">
                <div className="absolute top-1/2 left-0 w-full border-t border-dashed border-border/20"></div>
              </div>
            </div>
          ))}

          {/* "Now" line */}
          {nowIndicator !== null && (
            <div
              className="absolute left-16 lg:left-20 right-0 z-20 pointer-events-none flex items-center"
              style={{ top: `${nowIndicator}px` }}
            >
              <div className="w-2.5 h-2.5 rounded-full bg-red-500 -ml-[5px] shadow-md shadow-red-500/50"></div>
              <div className="flex-1 border-t-2 border-red-500/70"></div>
            </div>
          )}

          {/* Appointment blocks */}
          <div className="absolute top-0 left-16 lg:left-20 right-0 bottom-0 pointer-events-none">
            {enrichedAppointments.length === 0 && !isLoading && (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground/50">
                <CalendarOff className="h-12 w-12 mb-3 opacity-30" />
                <p className="text-sm font-medium">Nenhum agendamento</p>
                <p className="text-xs">Selecione outra data ou aguarde a Sofia agendar.</p>
              </div>
            )}

            {enrichedAppointments.map((appt) => {
              const isCancelled = appt.status === "CANCELLED";

              let accentColor = "border-l-blue-500";
              let bgColor = "bg-blue-500/10 hover:bg-blue-500/15";
              let badgeColor = "bg-blue-500/20 text-blue-400";
              let statusLabel = "Agendado";

              if (appt.status === "CONFIRMED") {
                accentColor = "border-l-emerald-500";
                bgColor = "bg-emerald-500/10 hover:bg-emerald-500/15";
                badgeColor = "bg-emerald-500/20 text-emerald-400";
                statusLabel = "Confirmado";
              } else if (appt.status === "COMPLETED") {
                accentColor = "border-l-slate-400";
                bgColor = "bg-slate-500/10 hover:bg-slate-500/15";
                badgeColor = "bg-slate-500/20 text-slate-400";
                statusLabel = "Concluído";
              } else if (isCancelled) {
                accentColor = "border-l-red-500";
                bgColor = "bg-red-500/8 hover:bg-red-500/12";
                badgeColor = "bg-red-500/20 text-red-400";
                statusLabel = "Cancelado";
              } else if (appt.status === "NO_SHOW") {
                accentColor = "border-l-amber-500";
                bgColor = "bg-amber-500/10 hover:bg-amber-500/15";
                badgeColor = "bg-amber-500/20 text-amber-400";
                statusLabel = "Não compareceu";
              }

              return (
                <div
                  key={appt.id}
                  className={cn(
                    "absolute left-2 right-3 rounded-lg border-l-[3px] shadow-sm pointer-events-auto cursor-pointer transition-all duration-200 group overflow-hidden",
                    accentColor,
                    bgColor,
                    isCancelled && "opacity-50 line-through"
                  )}
                  style={{
                    top: `${appt.topPos}px`,
                    height: `${appt.height}px`,
                  }}
                  title={`${appt.contactName} — ${appt.serviceName}`}
                >
                  <div className="flex flex-col justify-center h-full px-3 py-1.5 gap-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className={cn("font-semibold text-sm truncate text-foreground", isCancelled && "line-through")}>{appt.contactName}</span>
                      <span className={cn("text-[9px] px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wider shrink-0", badgeColor)}>
                        {statusLabel}
                      </span>
                    </div>

                    {appt.height >= 52 && (
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {format(appt.scheduledAt, "HH:mm")} · {appt.durationMins}min
                        </span>
                        <span className="flex items-center gap-1 truncate">
                          <User className="w-3 h-3" />
                          {appt.serviceName}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
