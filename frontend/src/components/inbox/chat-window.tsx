"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Contact, Message, useMessages, useSendMessage, useSendMedia, useUpdateContact, useSuggestReply, isInHumanTakeover } from "@/hooks/useInbox";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  Bot, Phone, Send, User, PauseCircle, PlayCircle, Loader2,
  Mic, Square, Paperclip, Image as ImageIcon, FileText, X, Download, Sparkles, UserCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { format, isToday, isYesterday } from "date-fns";
import { ptBR } from "date-fns/locale";

// WhatsApp-style day divider label
function dayLabel(d: Date): string {
  if (isToday(d)) return "Hoje";
  if (isYesterday(d)) return "Ontem";
  return format(d, "dd 'de' MMMM 'de' yyyy", { locale: ptBR });
}

// Render the appropriate bubble content for a message:
//  - new media (media_url set): pick by media_type
//  - legacy outbound audio (content starts with "data:audio/"): inline audio
//  - everything else: plain text
function MessageContent({
  msg,
  onOpenImage,
}: {
  msg: Message;
  onOpenImage: (url: string) => void;
}) {
  if (msg.media_url) {
    if (msg.media_type === "audio") {
      return (
        <audio controls className="max-w-[240px] h-10">
          <source src={msg.media_url} type={msg.media_mime_type || "audio/ogg"} />
        </audio>
      );
    }
    if (msg.media_type === "image") {
      return (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => onOpenImage(msg.media_url!)}
            className="block overflow-hidden rounded-lg"
          >
            <img
              src={msg.media_url}
              alt={msg.content || "Imagem"}
              className="max-w-[280px] max-h-[280px] object-cover hover:opacity-90 transition-opacity cursor-zoom-in"
            />
          </button>
          {msg.content && (
            <p className="whitespace-pre-wrap leading-relaxed text-sm">{msg.content}</p>
          )}
        </div>
      );
    }
    if (msg.media_type === "video") {
      return (
        <div className="flex flex-col gap-1">
          <video controls className="max-w-[280px] max-h-[280px] rounded-lg">
            <source src={msg.media_url} type={msg.media_mime_type || "video/mp4"} />
          </video>
          {msg.content && (
            <p className="whitespace-pre-wrap leading-relaxed text-sm">{msg.content}</p>
          )}
        </div>
      );
    }
    if (msg.media_type === "document") {
      const fileName = msg.content || "documento";
      return (
        <div className="flex flex-col gap-1">
          <a
            href={msg.media_url}
            download={fileName}
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border/50 bg-background/50 hover:bg-background transition-colors max-w-[260px]"
          >
            <FileText className="h-5 w-5 shrink-0 opacity-70" />
            <span className="truncate text-sm flex-1">{fileName}</span>
            <Download className="h-4 w-4 shrink-0 opacity-50" />
          </a>
        </div>
      );
    }
  }

  // Legacy: outbound audio stored directly in content as data URI
  if (msg.content.startsWith("data:audio/")) {
    return (
      <audio controls className="max-w-[240px] h-10">
        <source src={msg.content} type="audio/webm" />
      </audio>
    );
  }

  return <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>;
}

interface ChatWindowProps {
  contact: Contact;
}

export function ChatWindow({ contact }: ChatWindowProps) {
  const { data: messages, isLoading } = useMessages(contact.id);
  const { mutate: sendMessage, isPending: isSending } = useSendMessage();
  const { mutate: sendMedia, isPending: isSendingMedia } = useSendMedia();
  const { mutate: updateContact, isPending: isUpdatingStatus } = useUpdateContact();
  const { mutate: suggestReply, isPending: isSuggesting } = useSuggestReply();
  const [inputText, setInputText] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const hasScrolledRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Audio recording state
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Attachment menu
  const [showAttachMenu, setShowAttachMenu] = useState(false);

  // Image lightbox (click on inbound image to expand)
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);

  const isBusy = isSending || isSendingMedia;

  // Scroll to bottom on initial load
  useEffect(() => {
    hasScrolledRef.current = false;
  }, [contact.id]);

  useEffect(() => {
    if (!isLoading && messages && scrollContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
      // If user is within 150px from the bottom, or if it's the first load
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 150;
      
      if (!hasScrolledRef.current || isAtBottom) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
        hasScrolledRef.current = true;
      }
    }
  }, [messages, isLoading]);

  const pauseAIIfNeeded = useCallback(() => {
    if (!contact.ai_paused) {
      updateContact({ id: contact.id, data: { ai_paused: true } });
    }
  }, [contact.ai_paused, contact.id, updateContact]);

  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      setTimeout(() => {
        if (scrollContainerRef.current) {
          scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
        }
      }, 200);
    }
  }, []);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || isBusy) return;

    sendMessage(
      { contactId: contact.id, content: inputText },
      {
        onSuccess: () => {
          setInputText("");
          pauseAIIfNeeded();
          scrollToBottom();
          inputRef.current?.focus();
        },
        onError: () => alert("Erro ao enviar mensagem."),
      }
    );
  };

  const handleToggleAI = () => {
    updateContact({ id: contact.id, data: { ai_paused: !contact.ai_paused } });
  };

  // Staff copilot: ask Sofia to draft a reply and drop it into the input for
  // the human to review/edit before sending. Read-only on the backend — this
  // never sends or persists anything on its own.
  const handleSuggest = () => {
    if (isSuggesting || isBusy) return;
    suggestReply(contact.id, {
      onSuccess: (suggestion) => {
        if (suggestion?.trim()) {
          setInputText(suggestion);
          inputRef.current?.focus();
        } else {
          alert("A Sofia não conseguiu sugerir uma resposta para esta conversa.");
        }
      },
      onError: () => alert("Não consegui gerar uma sugestão agora. Tente de novo em instantes."),
    });
  };

  // ── Audio Recording ───────────────────────────────────────────────────
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        sendAudioBlob(blob);
      };

      mediaRecorder.start();
      setIsRecording(true);
      setRecordingTime(0);
      recordingTimerRef.current = setInterval(() => {
        setRecordingTime((t) => t + 1);
      }, 1000);
    } catch {
      alert("Não foi possível acessar o microfone. Verifique as permissões do navegador.");
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
  };

  const cancelRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onstop = () => {
        mediaRecorderRef.current?.stream.getTracks().forEach((t) => t.stop());
      };
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
    setRecordingTime(0);
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
  };

  const sendAudioBlob = (blob: Blob) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const base64 = reader.result as string;
      sendMedia(
        { contactId: contact.id, media_type: "audio", media: base64 },
        {
          onSuccess: () => { pauseAIIfNeeded(); scrollToBottom(); },
          onError: () => alert("Erro ao enviar áudio."),
        }
      );
    };
    reader.readAsDataURL(blob);
  };

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

  // ── File Attachment ───────────────────────────────────────────────────
  const handleFileSelect = (accept: string) => {
    setShowAttachMenu(false);
    if (fileInputRef.current) {
      fileInputRef.current.accept = accept;
      fileInputRef.current.click();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onloadend = () => {
      const base64 = reader.result as string;
      const isImage = file.type.startsWith("image/");
      sendMedia(
        {
          contactId: contact.id,
          media_type: isImage ? "image" : "document",
          media: base64,
          file_name: file.name,
        },
        {
          onSuccess: () => { pauseAIIfNeeded(); scrollToBottom(); },
          onError: () => alert("Erro ao enviar arquivo."),
        }
      );
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  // Messages arrive from backend most recent first — reverse for UI
  const displayMessages = messages ? [...messages].reverse() : [];

  // Staff replied by hand from their own phone: Sofia is deliberately quiet
  // until this lapses (see Contact.human_takeover_until).
  const inHumanTakeover = isInHumanTakeover(contact);
  const takeoverUntilLabel = contact.human_takeover_until
    ? format(new Date(contact.human_takeover_until), "HH:mm")
    : "";

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-background/10">
      {/* ── Header ── */}
      <div className="flex-shrink-0 flex items-center gap-4 p-4 border-b border-white/10 bg-background/45 backdrop-blur-md z-10">
        <Avatar className="h-10 w-10 border border-white/10 flex-shrink-0">
          <AvatarImage src={contact.profile_picture_url || ""} />
          <AvatarFallback className="bg-primary/5 text-primary">
            <User className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
        <div className="flex flex-col flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-heading font-semibold text-sm text-foreground truncate">{contact.full_name}</span>
            {contact.whatsapp_name && contact.whatsapp_name !== contact.full_name && (
              <span className="text-[10px] text-muted-foreground truncate opacity-70">~{contact.whatsapp_name}</span>
            )}
          </div>
          <div className="flex items-center text-[11px] text-muted-foreground gap-1 mt-0.5 opacity-80">
            <Phone className="h-3 w-3" />
            <span className="font-mono">{contact.phone || "Sem telefone"}</span>
          </div>
        </div>

        {/* AI Handoff Toggle */}
        <div className="flex items-center gap-3 bg-background/30 px-3 py-2 rounded-xl border border-white/10">
          <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground opacity-80">Secretária IA:</span>
          <button
            onClick={handleToggleAI}
            disabled={isUpdatingStatus}
            title={
              inHumanTakeover && !contact.ai_paused
                ? `Alguém da equipe respondeu este paciente pelo celular, então a Sofia está esperando até ${takeoverUntilLabel}. Ela volta sozinha.`
                : undefined
            }
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer",
              contact.ai_paused
                ? "bg-amber-500/10 text-amber-500 border border-amber-500/20 hover:bg-amber-500/20"
                : inHumanTakeover
                ? "bg-sky-500/10 text-sky-400 border border-sky-500/20 hover:bg-sky-500/20"
                : "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 hover:bg-emerald-500/20",
              isUpdatingStatus && "opacity-50 cursor-not-allowed"
            )}
          >
            {isUpdatingStatus ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : contact.ai_paused ? (
              <><PauseCircle className="h-3.5 w-3.5" /> Pausada</>
            ) : inHumanTakeover ? (
              <><UserCheck className="h-3.5 w-3.5" /> Aguardando até {takeoverUntilLabel}</>
            ) : (
              <><PlayCircle className="h-3.5 w-3.5" /> Ativa</>
            )}
          </button>
        </div>
      </div>

      {/* Human-takeover banner. Without this the header read "Ativa" while Sofia
          was deliberately silent, and nobody could tell why the patient wasn't
          being answered. */}
      {inHumanTakeover && !contact.ai_paused && (
        <div className="flex-shrink-0 flex items-start gap-2.5 px-4 py-2.5 bg-sky-500/5 border-b border-sky-500/15">
          <UserCheck className="h-4 w-4 text-sky-400 shrink-0 mt-0.5" />
          <p className="text-xs text-sky-100/80 font-sans leading-relaxed">
            Alguém da equipe respondeu este paciente direto pelo celular, então a{" "}
            <strong className="font-semibold">Sofia está em silêncio até {takeoverUntilLabel}</strong>{" "}
            para não falar por cima. Ela volta a responder sozinha depois disso; cada nova mensagem
            enviada à mão reinicia essa espera.
          </p>
        </div>
      )}

      {/* ── Messages ── */}
      <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col space-y-4">
        {isLoading ? (
          <div className="flex flex-col gap-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[70%] rounded-2xl p-4 animate-pulse border border-white/5",
                  i % 2 === 0
                    ? "bg-primary/10 self-end rounded-br-none"
                    : "bg-white/5 self-start rounded-bl-none"
                )}
              >
                <div className="h-4 w-32 bg-white/5 rounded mb-2" />
                <div className="h-3 w-20 bg-white/5 rounded" />
              </div>
            ))}
          </div>
        ) : displayMessages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground/50">
            <Bot className="h-12 w-12 mb-4 opacity-30 animate-pulse" />
            <p className="font-heading text-sm font-semibold">Nenhuma mensagem ainda</p>
            <p className="text-xs mt-1">A conversa está vazia.</p>
          </div>
        ) : (
          <>
            <div className="flex-1" />
            <div className="flex flex-col gap-3">
              {displayMessages.map((msg, idx) => {
                const isOutbound = msg.direction?.toUpperCase() === "OUTBOUND";
                const isAI = msg.ai_model_used != null;
                const msgDate = new Date(msg.created_at);
                const prev = displayMessages[idx - 1];
                const showDaySep =
                  !prev || new Date(prev.created_at).toDateString() !== msgDate.toDateString();
                return (
                  <div key={msg.id} className="contents">
                  {showDaySep && (
                    <div className="self-center my-3">
                      <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/80 bg-white/5 border border-white/5 rounded-full px-3 py-1">
                        {dayLabel(msgDate)}
                      </span>
                    </div>
                  )}
                  <div
                    className={cn(
                      "flex flex-col max-w-[80%] relative",
                      isOutbound ? "self-end items-end" : "self-start items-start"
                    )}
                  >
                    <div
                      className={cn(
                        "px-4 py-2.5 rounded-2xl text-sm shadow-md font-sans border",
                        isOutbound
                          ? "bg-primary text-primary-foreground border-primary/20 rounded-br-none"
                          : "bg-white/5 border-white/10 text-foreground rounded-bl-none"
                      )}
                    >
                      <MessageContent msg={msg} onOpenImage={setLightboxImage} />
                    </div>
                    <div className="flex items-center gap-1 mt-1.5 px-1 text-[10px] text-muted-foreground/60 font-mono">
                      <span>{format(new Date(msg.created_at), "HH:mm")}</span>
                      {isOutbound && isAI && (
                        <span className="flex items-center gap-1 ml-1.5 text-primary/80 font-semibold uppercase tracking-wider text-[9px]">
                          <Bot className="h-3 w-3" /> Sofia
                        </span>
                      )}
                      {isOutbound && !isAI && (
                        <span className="flex items-center gap-1 ml-1.5 text-muted-foreground font-semibold uppercase tracking-wider text-[9px]">
                          <User className="h-3 w-3" /> Equipe
                        </span>
                      )}
                    </div>
                  </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* ── Input Bar (WhatsApp Web style) ── */}
      <div className="flex-shrink-0 bg-background/45 backdrop-blur-md border-t border-white/10 p-3">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={handleFileChange}
        />

        {isRecording ? (
          /* ── Recording Mode ── */
          <div className="flex items-center gap-3">
            <button
              onClick={cancelRecording}
              className="h-10 w-10 rounded-full flex items-center justify-center text-destructive hover:bg-destructive/10 transition-colors cursor-pointer"
              title="Cancelar"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex-1 flex items-center gap-3 bg-destructive/5 border border-destructive/10 rounded-full px-4 py-2">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-sm font-mono text-destructive font-semibold">
                {formatTime(recordingTime)}
              </span>
              <span className="text-xs text-muted-foreground">Gravando áudio...</span>
            </div>

            <button
              onClick={stopRecording}
              className="h-11 w-11 rounded-full bg-primary flex items-center justify-center text-primary-foreground shadow-lg shadow-primary/25 hover:brightness-110 transition-all active:scale-95 cursor-pointer"
              title="Enviar áudio"
            >
              <Send className="h-5 w-5 ml-0.5" />
            </button>
          </div>
        ) : (
          /* ── Normal Mode ── */
          <div className="flex flex-col gap-2">
            {/* Staff copilot: draft a reply with Sofia, then edit before sending */}
            <div className="flex">
              <button
                type="button"
                onClick={handleSuggest}
                disabled={isSuggesting || isBusy}
                title="A Sofia escreve um rascunho de resposta pra você revisar e enviar"
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1.5 text-[11px] font-semibold text-primary transition-all hover:bg-primary/10 active:scale-95 cursor-pointer",
                  (isSuggesting || isBusy) && "opacity-50 cursor-not-allowed"
                )}
              >
                {isSuggesting ? (
                  <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Sofia está escrevendo...</>
                ) : (
                  <><Sparkles className="h-3.5 w-3.5" /> Sugerir resposta</>
                )}
              </button>
            </div>
          <form onSubmit={handleSend} className="flex items-center gap-2">
            {/* Attachment Button */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowAttachMenu((v) => !v)}
                className="h-10 w-10 rounded-full flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors cursor-pointer"
                title="Anexar"
              >
                <Paperclip className="h-5 w-5" />
              </button>

              {showAttachMenu && (
                <div className="absolute bottom-12 left-0 bg-background border border-white/10 rounded-2xl shadow-2xl p-2 flex flex-col gap-1 min-w-[160px] z-20 animate-in slide-in-from-bottom-2 duration-200">
                  <button
                    type="button"
                    onClick={() => handleFileSelect("image/*")}
                    className="flex items-center gap-3 px-3 py-2 text-sm rounded-lg hover:bg-white/5 transition-colors text-left text-foreground cursor-pointer font-sans"
                  >
                    <ImageIcon className="h-4 w-4 text-emerald-500" />
                    Fotos
                  </button>
                  <button
                    type="button"
                    onClick={() => handleFileSelect(".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv")}
                    className="flex items-center gap-3 px-3 py-2 text-sm rounded-lg hover:bg-white/5 transition-colors text-left text-foreground cursor-pointer font-sans"
                  >
                    <FileText className="h-4 w-4 text-blue-500" />
                    Documento
                  </button>
                </div>
              )}
            </div>

            {/* Text Input */}
            <input
              ref={inputRef}
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onFocus={() => setShowAttachMenu(false)}
              placeholder="Digitar mensagem..."
              className="flex-1 bg-background/55 border border-white/10 rounded-full px-5 h-11 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all text-foreground font-sans"
              disabled={isBusy}
            />

            {/* Send or Mic Button */}
            {inputText.trim() ? (
              <Button
                type="submit"
                size="icon"
                className="rounded-full h-11 w-11 shrink-0 shadow-lg shadow-primary/20 cursor-pointer"
                disabled={isBusy}
              >
                {isBusy ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Send className="h-5 w-5 ml-0.5" />
                )}
              </Button>
            ) : (
              <button
                type="button"
                onClick={startRecording}
                disabled={isBusy}
                className={cn(
                  "h-11 w-11 rounded-full flex items-center justify-center shrink-0 transition-colors cursor-pointer",
                  "text-muted-foreground hover:text-foreground hover:bg-white/5",
                  isBusy && "opacity-50 cursor-not-allowed"
                )}
                title="Gravar áudio"
              >
                <Mic className="h-5 w-5" />
              </button>
            )}
          </form>
          </div>
        )}
      </div>

      {/* Image lightbox — opens when an inbound image is clicked */}
      <Dialog open={lightboxImage !== null} onOpenChange={(open) => !open && setLightboxImage(null)}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] p-2 bg-black/95 border-0">
          {lightboxImage && (
            <img
              src={lightboxImage}
              alt="Imagem em tamanho real"
              className="w-full h-auto max-h-[85vh] object-contain"
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
