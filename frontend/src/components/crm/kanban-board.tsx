"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { CrmContact, CrmStage, useMoveCrmStage } from "@/hooks/useCrm";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { User, Bot, GripVertical } from "lucide-react";
import { cn } from "@/lib/utils";

const STAGES: { id: CrmStage; label: string; accent: string; dot: string }[] = [
  { id: "new_lead", label: "Novo Lead", accent: "border-t-slate-500", dot: "bg-slate-500" },
  { id: "in_conversation", label: "Em conversa", accent: "border-t-primary", dot: "bg-primary" },
  { id: "scheduled", label: "Agendado", accent: "border-t-amber-500", dot: "bg-amber-500" },
  { id: "attended", label: "Compareceu", accent: "border-t-emerald-500", dot: "bg-emerald-500" },
  { id: "post_care", label: "Pós-atendimento", accent: "border-t-purple-500", dot: "bg-purple-500" },
  { id: "lost", label: "Perdido", accent: "border-t-destructive", dot: "bg-destructive" },
];

function initialsOf(name: string) {
  return name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);
}

function previewOf(msg?: CrmContact["last_message"]) {
  if (!msg) return "Sem mensagens";
  switch (msg.media_type) {
    case "audio": return "🎤 Áudio";
    case "image": return "📷 Foto";
    case "video": return "🎬 Vídeo";
    case "document": return "📄 Documento";
    default: return msg.content || "Mensagem";
  }
}

function Card({ contact, overlay = false }: { contact: CrmContact; overlay?: boolean }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: contact.id,
  });
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded-xl border border-white/10 bg-background/55 backdrop-blur-md p-3 shadow-md select-none transition-all hover:border-primary/20",
        isDragging && !overlay && "opacity-40",
        overlay && "shadow-2xl ring-1 ring-primary/30 rotate-1 bg-background/95 border-white/20",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          {...listeners}
          {...attributes}
          className="mt-0.5 text-muted-foreground/40 hover:text-muted-foreground cursor-grab active:cursor-grabbing touch-none h-6 w-6 flex items-center justify-center rounded hover:bg-white/5 transition-all"
          aria-label="Arrastar"
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <Avatar className="h-8 w-8 border border-white/10 flex-shrink-0">
          <AvatarImage src={contact.profile_picture_url || ""} />
          <AvatarFallback className="bg-primary/5 text-primary text-xs font-mono">
            {initialsOf(contact.full_name)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <p className="font-heading text-sm font-semibold truncate text-foreground leading-tight">{contact.full_name}</p>
          <p className="text-xs text-muted-foreground truncate opacity-85 mt-1 font-sans">{previewOf(contact.last_message)}</p>
          {contact.crm_stage_source === "ai" && (
            <span className="mt-2 inline-flex items-center gap-1 text-[9px] font-mono uppercase tracking-wider text-primary/70 font-semibold">
              <Bot className="h-3 w-3 animate-pulse text-primary" /> Sofia AI
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function Column({
  stage,
  contacts,
}: {
  stage: (typeof STAGES)[number];
  contacts: CrmContact[];
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  return (
    <div className="flex flex-col w-72 shrink-0">
      <div className={cn("rounded-t-xl border-t-4 bg-background/55 border-x border-white/10 px-4 py-3 flex items-center justify-between", stage.accent)}>
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", stage.dot)} />
          <span className="font-heading text-xs font-semibold uppercase tracking-wider text-foreground">{stage.label}</span>
        </div>
        <span className="text-[10px] font-mono text-muted-foreground bg-white/5 border border-white/5 rounded-full px-2 py-0.5">
          {contacts.length}
        </span>
      </div>
      <div
        ref={setNodeRef}
        className={cn(
          "flex-1 min-h-[250px] rounded-b-xl border-x border-b border-white/10 p-2.5 space-y-2.5 transition-colors overflow-y-auto bg-background/15 backdrop-blur-md shadow-xl",
          isOver ? "bg-primary/5" : "bg-background/5",
        )}
      >
        {contacts.length === 0 ? (
          <p className="text-xs text-muted-foreground/40 text-center py-8 font-sans">Sem contatos</p>
        ) : (
          contacts.map((c) => <Card key={c.id} contact={c} />)
        )}
      </div>
    </div>
  );
}

export function KanbanBoard({ contacts }: { contacts: CrmContact[] }) {
  const move = useMoveCrmStage();
  const [activeId, setActiveId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  const onDragStart = (e: DragStartEvent) => setActiveId(e.active.id as string);
  const onDragEnd = (e: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = e;
    if (!over) return;
    const contact = contacts.find((c) => c.id === active.id);
    const target = over.id as CrmStage;
    if (contact && contact.crm_stage !== target) {
      move.mutate({ id: contact.id, crm_stage: target });
    }
  };

  const activeContact = activeId ? contacts.find((c) => c.id === activeId) : null;

  return (
    <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
      <div className="flex gap-4 overflow-x-auto pb-4 h-full">
        {STAGES.map((s) => (
          <Column key={s.id} stage={s} contacts={contacts.filter((c) => c.crm_stage === s.id)} />
        ))}
      </div>
      <DragOverlay>{activeContact ? <Card contact={activeContact} overlay /> : null}</DragOverlay>
    </DndContext>
  );
}
