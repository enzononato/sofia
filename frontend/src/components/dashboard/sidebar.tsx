"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  MessageSquare,
  Calendar,
  Stethoscope,
  Users,
  Settings,
  Bot
} from "lucide-react";

const navigation = [
  { name: "Inbox", href: "/dashboard/inbox", icon: MessageSquare },
  { name: "Calendário", href: "/dashboard/calendar", icon: Calendar },
  { name: "Serviços", href: "/dashboard/services", icon: Stethoscope },
  { name: "Equipe", href: "/dashboard/team", icon: Users },
  { name: "Configurações", href: "/dashboard/settings", icon: Settings },
];

export function Sidebar({ className }: { className?: string }) {
  const pathname = usePathname();

  return (
    <div className={cn("hidden border-r border-border/50 bg-card/30 backdrop-blur-md md:block w-64 h-full", className)}>
      <div className="flex h-full max-h-screen flex-col gap-2">
        <div className="flex h-[60px] items-center border-b border-border/50 px-6">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold tracking-tight">
            <div className="w-8 h-8 bg-primary/20 text-primary rounded-lg flex items-center justify-center ring-1 ring-primary/30">
              <Bot size={20} />
            </div>
            <span className="text-lg">Sofia</span>
          </Link>
        </div>
        <div className="flex-1 overflow-auto py-4">
          <nav className="grid items-start px-4 text-sm font-medium gap-1">
            {navigation.map((item) => {
              const isActive = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 transition-all",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <item.icon className={cn("h-4 w-4", isActive ? "text-primary" : "")} />
                  {item.name}
                </Link>
              );
            })}
          </nav>
        </div>
        
        {/* Espaço reservado para plano ou algo extra na base */}
        <div className="mt-auto p-4">
          <div className="rounded-xl border border-border/50 bg-card p-4 shadow-sm">
            <p className="text-xs font-medium text-foreground">Plano Pro</p>
            <p className="text-[10px] text-muted-foreground mt-1">Sua clínica está otimizada com IA.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
