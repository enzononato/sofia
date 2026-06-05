"use client";

import { useState } from "react";
import { ContactList } from "./contact-list";
import { ChatWindow } from "./chat-window";
import { useContacts } from "@/hooks/useInbox";

export function InboxLayout() {
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);
  const { data: contacts, isLoading, error } = useContacts();

  return (
    <div className="flex h-[calc(100vh-60px)] w-full overflow-hidden bg-background">
      {/* Left Column: Contacts */}
      <div className="w-full md:w-80 lg:w-96 border-r border-border/50 flex-shrink-0">
        <ContactList 
          contacts={contacts || []} 
          isLoading={isLoading} 
          selectedId={selectedContactId}
          onSelect={setSelectedContactId} 
        />
      </div>

      {/* Right Column: Chat Window */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden bg-muted/10 relative">
        {selectedContactId ? (
          <ChatWindow 
            contact={contacts!.find(c => c.id === selectedContactId)!} 
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4 ring-1 ring-primary/20">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary"><path d="m3 21 1.9-5.7a8.5 8.5 0 1 1 3.8 3.8z"/></svg>
            </div>
            <h3 className="text-lg font-medium text-foreground">Inbox da Sofia</h3>
            <p className="text-sm max-w-sm mt-2">
              Selecione um contato ao lado para visualizar a conversa e interagir manualmente.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
