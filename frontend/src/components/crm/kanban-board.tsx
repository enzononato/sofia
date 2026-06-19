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
  { id: "new_lead", label: "Novo Lead", accent: "border-t-slate-400", dot: "bg-slate-400" },
  { id: "in_conversation", label: "Em conversa", accent: "border-t-blue-400", dot: "bg-blue-400" },
  { id: "scheduled", label: "Agendado", accent: "border-t-amber-400", dot: "bg-amber-400" },
  { id: "attended", label: "Compareceu", accent: "border-t-emerald-400", dot: "bg-emerald-400" },
  { id: "post_care", label: "Pós-atendimento", accent: "border-t-violet-400", dot: "bg-violet-400" },
  { id: "lost", label: "Perdido", accent: "border-t-red-400", dot: "bg-red-400" },
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
        "rounded-lg border border-border/50 bg-card p-3 shadow-sm select-none",
        isDragging && !overlay && "opacity-40",
        overlay && "shadow-lg ring-1 ring-primary/30 rotate-1",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          {...listeners}
          {...attributes}
          className="mt-0.5 text-muted-foreground/50 hover:text-muted-foreground cursor-grab active:cursor-grabbing touch-none"
          aria-label="Arrastar"
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <Avatar className="h-8 w-8 border border-border/50">
          <AvatarImage src={contact.profile_picture_url || ""} />
          <AvatarFallback className="bg-primary/5 text-primary text-xs">
            {initialsOf(contact.full_name)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{contact.full_name}</p>
          <p className="text-xs text-muted-foreground truncate">{previewOf(contact.last_message)}</p>
          {contact.crm_stage_source === "ai" && (
            <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-primary/70">
              <Bot className="h-3 w-3" /> classificado pela Sofia
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
      <div className={cn("rounded-t-lg border-t-4 bg-card/60 px-3 py-2 flex items-center justify-between", stage.accent)}>
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", stage.dot)} />
          <span className="text-sm font-semibold">{stage.label}</span>
        </div>
        <span className="text-xs text-muted-foreground bg-muted rounded-full px-2 py-0.5">
          {contacts.length}
        </span>
      </div>
      <div
        ref={setNodeRef}
        className={cn(
          "flex-1 min-h-[200px] rounded-b-lg border border-t-0 border-border/50 p-2 space-y-2 transition-colors overflow-y-auto",
          isOver ? "bg-primary/5" : "bg-muted/20",
        )}
      >
        {contacts.length === 0 ? (
          <p className="text-xs text-muted-foreground/60 text-center py-6">Vazio</p>
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
