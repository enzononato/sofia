"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/useAuthStore";
import {
  MessageCircle,
  Calendar,
  Stethoscope,
  Users,
  Settings,
  Sparkles,
  KanbanSquare,
  BarChart3,
  Bolt,
} from "lucide-react";

// `adminOnly` items are hidden from professionals (owner/admin only).
const navigation = [
  { name: "Inbox", href: "/dashboard/inbox", icon: MessageCircle },
  { name: "CRM", href: "/dashboard/crm", icon: KanbanSquare },
  { name: "Calendário", href: "/dashboard/calendar", icon: Calendar },
  { name: "Relatórios", href: "/dashboard/reports", icon: BarChart3, adminOnly: true },
  { name: "Serviços", href: "/dashboard/services", icon: Stethoscope, adminOnly: true },
  { name: "Equipe", href: "/dashboard/team", icon: Users, adminOnly: true },
];

export function Sidebar({ className }: { className?: string }) {
  const pathname = usePathname();
  const userRole = useAuthStore((s) => s.userRole);
  const isAdmin = userRole === "owner" || userRole === "admin";
  const visibleNav = navigation.filter((item) => !item.adminOnly || isAdmin);

  return (
    <div
      className={cn(
        "hidden border-r border-white/10 bg-background/50 backdrop-blur-xl md:flex flex-col w-[280px] h-screen fixed left-0 top-0 z-50",
        className
      )}
    >
      <div className="flex h-full flex-col p-4 gap-2 flex-grow">
        {/* Header Section */}
        <div className="flex items-center gap-3 px-2 py-4">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#6d3bd7] to-[#ae05c6] flex items-center justify-center shadow-lg">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="font-heading text-[18px] font-bold text-primary leading-tight">
              Sofia AI
            </h1>
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground opacity-70">
              Assistente Inteligente
            </p>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="mt-6 flex flex-col gap-1 flex-1">
          {visibleNav.map((item) => {
            const isActive = pathname.startsWith(item.href);
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all active:scale-[0.98]",
                  isActive
                    ? "bg-primary/10 text-primary border-r-2 border-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <item.icon className={cn("h-4 w-4", isActive ? "text-primary" : "")} />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Footer Area */}
        <div className="p-2 border-t border-white/10 flex flex-col gap-1">
          <button className="w-full py-3 px-4 rounded-xl border border-white/10 bg-[rgba(30,41,59,0.45)] backdrop-blur-md text-foreground flex items-center justify-center gap-2 hover:shadow-lg hover:shadow-primary/10 transition-all font-semibold text-xs hover:scale-[1.02] active:scale-[0.98]">
            <Bolt className="h-4 w-4 text-primary animate-pulse" />
            <span>Pedir ajuda à Sofia</span>
          </button>
          
          <Link
            href="/dashboard/settings"
            className={cn(
              "flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all",
              pathname.startsWith("/dashboard/settings")
                ? "bg-primary/10 text-primary border-r-2 border-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            <Settings className="h-4 w-4" />
            <span>Configurações</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
