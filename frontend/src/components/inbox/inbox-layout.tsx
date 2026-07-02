"use client";

import { useState } from "react";
import { ContactList } from "./contact-list";
import { ChatWindow } from "./chat-window";
import { useContacts } from "@/hooks/useInbox";
import { Sparkles } from "lucide-react";

export function InboxLayout() {
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);
  const { data: contacts, isLoading, error } = useContacts();

  return (
    <div className="flex h-[calc(100vh-64px)] w-full overflow-hidden bg-background">
      {/* Left Column: Contacts */}
      <div className="w-full md:w-[360px] border-r border-white/10 flex flex-col flex-shrink-0 bg-background/15 backdrop-blur-md">
        <ContactList 
          contacts={contacts || []} 
          isLoading={isLoading} 
          selectedId={selectedContactId}
          onSelect={setSelectedContactId} 
        />
      </div>

      {/* Right Column: Chat Window */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden bg-background/5 relative">
        {selectedContactId ? (
          <ChatWindow 
            contact={contacts!.find(c => c.id === selectedContactId)!} 
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
            {/* Ambient inner glow */}
            <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
            
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4 ring-1 ring-primary/20 shadow-lg shadow-primary/5 animate-pulse">
              <Sparkles className="h-6 w-6 text-primary" />
            </div>
            <h3 className="font-heading text-xl font-bold text-foreground">Central de Mensagens</h3>
            <p className="text-sm max-w-sm mt-2 text-muted-foreground">
              Selecione uma conversa ao lado para visualizar o histórico de atendimento e interagir manualmente.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
