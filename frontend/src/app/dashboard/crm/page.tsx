"use client";

import { useCrmContacts } from "@/hooks/useCrm";
import { KanbanBoard } from "@/components/crm/kanban-board";
import { Loader2, KanbanSquare } from "lucide-react";

export default function CrmPage() {
  const { data, isLoading, isError } = useCrmContacts();

  return (
    <div className="flex flex-col h-full p-4 md:p-6 min-h-0 bg-background/5">
      <div className="mb-6 shrink-0">
        <h1 className="font-heading text-2xl font-bold tracking-tight flex items-center gap-2 text-foreground">
          <KanbanSquare className="h-6 w-6 text-primary" />
          CRM
        </h1>
        <p className="text-muted-foreground mt-1 text-sm font-sans">
          Funil de relacionamento. A Sofia classifica os pacientes automaticamente conforme a conversa —
          você também pode arrastar os cards entre as colunas.
        </p>
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <div className="p-4 border border-destructive/50 bg-destructive/5 text-destructive rounded-lg">
          Erro ao carregar o CRM. Verifique sua conexão.
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <KanbanBoard contacts={data || []} />
        </div>
      )}
    </div>
  );
}
