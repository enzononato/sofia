"use client";

import { useMemo } from "react";
import { format, differenceInMinutes, startOfDay, addHours, isToday, getISODay } from "date-fns";
import { Appointment, Service } from "@/hooks/useCalendar";
import { Contact } from "@/hooks/useInbox";
import { useUserDetail } from "@/hooks/useTeam";
import { cn } from "@/lib/utils";
import { Clock, User, CalendarOff } from "lucide-react";

interface DailyTimelineProps {
  date: Date;
  appointments: Appointment[];
  contacts: Contact[];
  services: Service[];
  isLoading: boolean;
  onSelect?: (appt: Appointment) => void;
  /** When set (a specific professional, not "Todos"), shades hours outside their work_hours. */
  professionalId?: string;
}

const START_HOUR = 7;
const END_HOUR = 19;
const ROW_HEIGHT = 72; // pixels per hour

/** "HH:MM" or "HH:MM:SS" → minutes since midnight. */
function timeToMinutes(t: string): number {
  const [h, m] = t.split(":");
  return parseInt(h, 10) * 60 + (m ? parseInt(m, 10) : 0);
}

export function DailyTimeline({ date, appointments, contacts, services, isLoading, onSelect, professionalId }: DailyTimelineProps) {
  // Only fetched when a specific professional is selected (useUserDetail is
  // disabled without an id) — the "Todos" case never triggers this request.
  const { data: professionalDetail, isLoading: isLoadingWorkHours } = useUserDetail(professionalId);

  // Segments of the visible [START_HOUR, END_HOUR] window that fall OUTSIDE
  // the selected professional's work_hours for the weekday of `date`, in
  // minutes relative to START_HOUR (same coordinate space as topPos below).
  // No fallback to clinic-wide hours here on purpose — that behaviour already
  // lives server-side (`_professional_work_blocks` in app/services/ai_tools.py);
  // the frontend only mirrors whatever useUserDetail returns.
  const offHoursSegments = useMemo(() => {
    if (!professionalId || isLoadingWorkHours) return [];
    const workHours = professionalDetail?.work_hours || [];
    const isoWeekday = getISODay(date);
    const dayBlocks = workHours.filter((b) => b.weekday === isoWeekday);

    const windowStart = START_HOUR * 60;
    const windowEnd = END_HOUR * 60;

    if (dayBlocks.length === 0) {
      // No work_hours registered for this weekday at all → treat as a full day off.
      return [{ start: 0, length: windowEnd - windowStart }];
    }

    const working = dayBlocks
      .map((b) => ({
        start: Math.max(timeToMinutes(b.start_time), windowStart),
        end: Math.min(timeToMinutes(b.end_time), windowEnd),
      }))
      .filter((b) => b.end > b.start)
      .sort((a, b) => a.start - b.start);

    const segments: { start: number; length: number }[] = [];
    let cursor = windowStart;
    for (const block of working) {
      if (block.start > cursor) {
        segments.push({ start: cursor - windowStart, length: block.start - cursor });
      }
      cursor = Math.max(cursor, block.end);
    }
    if (cursor < windowEnd) {
      segments.push({ start: cursor - windowStart, length: windowEnd - cursor });
    }
    return segments;
  }, [professionalId, isLoadingWorkHours, professionalDetail, date]);
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

          {/* Out-of-hours shading for the selected professional (skipped for "Todos") */}
          {professionalId && isLoadingWorkHours && (
            <div className="absolute top-0 left-16 lg:left-20 right-0 bottom-0 pointer-events-none animate-pulse bg-muted/20" />
          )}
          {professionalId && !isLoadingWorkHours && offHoursSegments.map((seg, i) => (
            <div
              key={i}
              className="absolute left-16 lg:left-20 right-0 pointer-events-none bg-muted-foreground/10"
              style={{
                top: `${(seg.start / 60) * ROW_HEIGHT}px`,
                height: `${(seg.length / 60) * ROW_HEIGHT}px`,
              }}
              title="Fora do expediente deste profissional"
            />
          ))}

          {/* "Now" line — violet with a time pill (matches Stitch mockup) */}
          {nowIndicator !== null && (
            <div
              className="absolute left-16 lg:left-20 right-0 z-20 pointer-events-none flex items-center"
              style={{ top: `${nowIndicator}px` }}
            >
              <div className="-ml-1 rounded bg-primary px-1.5 py-0.5 font-mono text-[10px] font-bold text-primary-foreground shadow-md shadow-primary/40">
                {format(new Date(), "HH:mm")}
              </div>
              <div className="flex-1 border-t-2 border-primary/60 shadow-[0_0_8px_rgba(208,188,255,0.6)]"></div>
              <div className="h-2 w-2 rounded-full bg-primary"></div>
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

              // Status → colour mapping mirrors the Stitch mockup: violet for
              // "Agendado", emerald for "Confirmado", cyan for "Compareceu",
              // rose for "Cancelado", amber for "Não compareceu".
              let accentColor = "border-l-primary";
              let bgColor = "bg-primary/10 hover:bg-primary/15";
              let badgeColor = "bg-primary/20 text-primary";
              let statusLabel = "Agendado";

              if (appt.status === "confirmed") {
                accentColor = "border-l-emerald-500";
                bgColor = "bg-emerald-500/10 hover:bg-emerald-500/15";
                badgeColor = "bg-emerald-500/20 text-emerald-400";
                statusLabel = "Confirmado";
              } else if (appt.status === "completed") {
                accentColor = "border-l-[#4cd7f6]";
                bgColor = "bg-[#4cd7f6]/10 hover:bg-[#4cd7f6]/15";
                badgeColor = "bg-[#4cd7f6]/20 text-[#4cd7f6]";
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
