"use client";

import { useState } from "react";
import { Contact } from "@/hooks/useInbox";
import { Search, User } from "lucide-react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { format, isToday, isYesterday } from "date-fns";

interface ContactListProps {
  contacts: Contact[];
  isLoading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ContactList({ contacts, isLoading, selectedId, onSelect }: ContactListProps) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "waiting">("all");

  const filteredContacts = contacts.filter((c) => {
    const matchesSearch = c.full_name.toLowerCase().includes(search.toLowerCase()) || 
                          (c.phone && c.phone.includes(search));
    if (!matchesSearch) return false;
    
    if (filter === "waiting") return c.ai_paused;
    return true;
  });

  const sortedContacts = [...filteredContacts].sort((a, b) => {
    const timeA = a.last_message ? new Date(a.last_message.created_at).getTime() : new Date(0).getTime();
    const timeB = b.last_message ? new Date(b.last_message.created_at).getTime() : new Date(0).getTime();
    return timeB - timeA; // Descending
  });

  const formatMessageTime = (dateString: string) => {
    const date = new Date(dateString);
    if (isToday(date)) {
      return format(date, "HH:mm");
    } else if (isYesterday(date)) {
      return "Ontem";
    } else {
      return format(date, "dd/MM/yyyy");
    }
  };

  const messagePreview = (msg: NonNullable<Contact["last_message"]>) => {
    switch (msg.media_type) {
      case "audio":
        return `🎤 Áudio${msg.content ? `: ${msg.content}` : ""}`;
      case "image":
        return `📷 Foto ${msg.content || ""}`;
      case "video":
        return `🎬 Vídeo ${msg.content || ""}`;
      case "document":
        return `📄 Documento ${msg.content || ""}`;
      default:
        return msg.content || "Mensagem";
    }
  };

  return (
    <div className="flex flex-col h-full bg-background/5">
      <div className="p-4 border-b border-white/10 sticky top-0 z-10 bg-background/45 backdrop-blur-md">
        <h2 className="font-heading text-lg font-bold tracking-tight mb-4 text-foreground">Conversas</h2>
        <div className="relative mb-3">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar paciente..."
            className="pl-10 h-10 bg-background/55 border-white/10 focus-visible:border-primary/50 focus-visible:ring-0 rounded-xl placeholder:text-muted-foreground/60 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setFilter("all")}
            className={cn(
              "text-[11px] font-mono uppercase tracking-wider px-3 py-1.5 rounded-full font-medium transition-all active:scale-95",
              filter === "all"
                ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                : "bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            )}
          >
            Todas
          </button>
          <button
            onClick={() => setFilter("waiting")}
            className={cn(
              "text-[11px] font-mono uppercase tracking-wider px-3 py-1.5 rounded-full font-medium transition-all active:scale-95",
              filter === "waiting"
                ? "bg-amber-500 text-white shadow-lg shadow-amber-500/20"
                : "bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            )}
          >
            Aguardando Humano
          </button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="p-4 space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-3 animate-pulse">
                <div className="w-12 h-12 rounded-full bg-white/5"></div>
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-white/5 rounded w-3/4"></div>
                  <div className="h-3 bg-white/5 rounded w-1/2"></div>
                </div>
              </div>
            ))}
          </div>
        ) : filteredContacts.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm font-sans">
            Nenhum paciente encontrado.
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {sortedContacts.map((contact) => {
              const isSelected = selectedId === contact.id;
              return (
                <button
                  key={contact.id}
                  onClick={() => onSelect(contact.id)}
                  className={cn(
                    "w-full flex items-start gap-3 p-3 rounded-xl transition-all text-left relative group",
                    isSelected
                      ? "bg-primary/10 border-white/10 ring-1 ring-primary/20"
                      : "hover:bg-white/5 border border-transparent"
                  )}
                >
                  {/* Left Indicator */}
                  {isSelected && (
                    <div className="absolute left-0 top-3 bottom-3 w-[3px] bg-primary rounded-r" />
                  )}

                  <Avatar className="h-12 w-12 border border-white/10 flex-shrink-0">
                    <AvatarImage src={contact.profile_picture_url || ""} />
                    <AvatarFallback className="bg-primary/5 text-primary">
                      <User className="h-5 w-5" />
                    </AvatarFallback>
                  </Avatar>
                  
                  <div className="flex-1 overflow-hidden min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex flex-col min-w-0">
                        <span className="font-heading font-semibold text-sm truncate text-foreground leading-tight">
                          {contact.full_name}
                        </span>
                        {contact.whatsapp_name && contact.whatsapp_name !== contact.full_name && (
                          <span className="text-[10px] text-muted-foreground truncate mt-0.5 opacity-70">
                            ~{contact.whatsapp_name}
                          </span>
                        )}
                      </div>
                      {contact.last_message && (
                        <span className="text-[10px] font-mono text-muted-foreground/60 flex-shrink-0 self-start mt-0.5 font-medium">
                          {formatMessageTime(contact.last_message.created_at)}
                        </span>
                      )}
                    </div>
                    
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-xs text-muted-foreground truncate flex-1 opacity-80 font-sans">
                        {contact.last_message ? messagePreview(contact.last_message) : "Nenhuma mensagem ainda."}
                      </p>
                      {contact.ai_paused && (
                        <span className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0 animate-pulse" title="Aguardando Humano" />
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
