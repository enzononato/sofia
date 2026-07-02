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
  onSelect?: (appt: Appointment) => void;
}

const START_HOUR = 7;
const END_HOUR = 19;
const ROW_HEIGHT = 72; // pixels per hour

export function DailyTimeline({ date, appointments, contacts, services, isLoading, onSelect }: DailyTimelineProps) {
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
    <div className="relative min-h-full p-4 lg:px-8 lg:py-6 bg-background/5">
      <div className="relative rounded-2xl border border-white/10 bg-background/40 backdrop-blur-md shadow-xl overflow-hidden">

        {/* Hour rows */}
        <div className="relative">
          {hours.map((hour, idx) => (
            <div
              key={hour.toISOString()}
              className={cn(
                "flex items-start",
                idx !== hours.length - 1 && "border-b border-white/10"
              )}
              style={{ height: ROW_HEIGHT }}
            >
              {/* Hour label */}
              <div className="w-16 lg:w-20 pr-3 pt-1.5 text-right font-mono text-[10px] text-muted-foreground/70 border-r border-white/10 h-full select-none">
                {format(hour, "HH:mm")}
              </div>
              {/* Slot area */}
              <div className="flex-1 relative">
                <div className="absolute top-1/2 left-0 w-full border-t border-dashed border-white/5"></div>
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
              <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground/40">
                <CalendarOff className="h-12 w-12 mb-3 opacity-30" />
                <p className="font-heading text-sm font-semibold">Nenhum compromisso agendado</p>
                <p className="text-xs mt-1">Selecione outra data ou aguarde a Sofia responder pacientes.</p>
              </div>
            )}

            {enrichedAppointments.map((appt) => {
              const isCancelled = appt.status === "cancelled";

              let accentColor = "border-l-primary";
              let bgColor = "bg-primary/10 hover:bg-primary/15";
              let badgeColor = "bg-primary/20 text-primary";
              let statusLabel = "Agendado";

              if (appt.status === "confirmed") {
                accentColor = "border-l-primary";
                bgColor = "bg-primary/10 hover:bg-primary/15";
                badgeColor = "bg-primary/20 text-primary";
                statusLabel = "Confirmado";
              } else if (appt.status === "completed") {
                accentColor = "border-l-emerald-500";
                bgColor = "bg-emerald-500/10 hover:bg-emerald-500/15";
                badgeColor = "bg-emerald-500/20 text-emerald-400";
                statusLabel = "Compareceu";
              } else if (isCancelled) {
                accentColor = "border-l-destructive";
                bgColor = "bg-destructive/5 hover:bg-destructive/10";
                badgeColor = "bg-destructive/20 text-destructive";
                statusLabel = "Cancelado";
              } else if (appt.status === "no_show") {
                accentColor = "border-l-amber-500";
                bgColor = "bg-amber-500/10 hover:bg-amber-500/15";
                badgeColor = "bg-amber-500/20 text-amber-400";
                statusLabel = "Não compareceu";
              }

              return (
                <div
                  key={appt.id}
                  onClick={() => onSelect?.(appt)}
                  className={cn(
                    "absolute left-2 right-3 rounded-xl border-l-[4px] shadow-lg pointer-events-auto cursor-pointer transition-all duration-200 group overflow-hidden border border-white/5 hover:scale-[1.005] hover:ring-1 hover:ring-primary/30",
                    accentColor,
                    bgColor,
                    isCancelled && "opacity-40 line-through"
                  )}
                  style={{
                    top: `${appt.topPos}px`,
                    height: `${appt.height}px`,
                  }}
                  title={`${appt.contactName} — ${appt.serviceName}`}
                >
                  <div className="flex flex-col justify-center h-full px-4 py-2 gap-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className={cn("font-heading font-semibold text-xs truncate text-foreground leading-tight", isCancelled && "line-through")}>
                        {appt.contactName}
                      </span>
                      <span className={cn("text-[9px] font-mono px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wider shrink-0", badgeColor)}>
                        {statusLabel}
                      </span>
                    </div>

                    {appt.height >= 52 && (
                      <div className="flex items-center gap-3 text-[10px] text-muted-foreground/80 font-sans mt-0.5">
                        <span className="flex items-center gap-1.5">
                          <Clock className="w-3.5 h-3.5 text-muted-foreground/60" />
                          {format(appt.scheduledAt, "HH:mm")} · {appt.durationMins} min
                        </span>
                        <span className="flex items-center gap-1.5 truncate">
                          <User className="w-3.5 h-3.5 text-muted-foreground/60" />
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
