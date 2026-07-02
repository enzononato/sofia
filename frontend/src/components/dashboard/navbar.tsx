"use client";

import { useAuthStore } from "@/store/useAuthStore";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { LogOut, Menu, User, Bell, Sparkles } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { Sidebar } from "./sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";

export function Navbar() {
  const { tenant, userEmail, userRole, logout } = useAuthStore();

  const handleLogout = () => {
    logout();
    window.location.href = "/login";
  };

  return (
    <header className="flex h-[64px] items-center gap-4 border-b border-white/10 bg-background/40 backdrop-blur-md px-6 shadow-sm sticky top-0 z-30">
      <Sheet>
        <SheetTrigger className="shrink-0 md:hidden inline-flex items-center justify-center rounded-md text-sm font-medium hover:bg-accent hover:text-accent-foreground h-10 w-10">
          <Menu className="h-5 w-5" />
          <span className="sr-only">Menu de navegação</span>
        </SheetTrigger>
        <SheetContent side="left" className="flex flex-col p-0 w-[280px] border-r border-white/10 bg-background">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <Sidebar className="block border-none" />
        </SheetContent>
      </Sheet>

      <div className="flex-1">
        <h1 className="font-heading text-lg font-bold tracking-tight text-foreground">
          {tenant?.name || "Sofia AI"}
        </h1>
      </div>

      <div className="flex items-center gap-6">
        {/* Decorative mockup icons */}
        <div className="hidden sm:flex items-center gap-4">
          <button className="text-muted-foreground hover:text-primary transition-colors flex items-center gap-1.5 text-xs font-semibold">
            <Sparkles className="h-4 w-4 text-primary animate-pulse" />
            <span className="font-mono uppercase tracking-wider text-[10px]">Sofia Insights</span>
          </button>
          <button className="text-muted-foreground hover:text-foreground transition-colors relative h-8 w-8 flex items-center justify-center rounded-full hover:bg-white/5">
            <Bell className="h-4 w-4" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-destructive rounded-full"></span>
          </button>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger className="flex items-center gap-3 pl-4 border-l border-white/10 hover:opacity-90 transition-opacity focus:outline-none cursor-pointer">
            <div className="text-right hidden sm:block">
              <p className="font-heading text-sm font-semibold text-foreground leading-none">{userEmail?.split("@")[0] || "usuário"}</p>
              <p className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest mt-1">
                {userRole === "owner" ? "Proprietário" : userRole === "admin" ? "Administrador" : "Profissional"}
              </p>
            </div>
            <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-primary to-[#4cd7f6] p-[2px]">
              <div className="w-full h-full rounded-full bg-background flex items-center justify-center overflow-hidden">
                <Avatar className="h-full w-full">
                  <AvatarImage src="" alt="Avatar" />
                  <AvatarFallback className="bg-background text-primary">
                    <User className="h-4 w-4" />
                  </AvatarFallback>
                </Avatar>
              </div>
            </div>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56 mt-2 border-white/10 bg-background/95 backdrop-blur-md" align="end">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col space-y-1">
                  <p className="text-sm font-medium leading-none truncate">{userEmail || "usuário"}</p>
                  <p className="text-[10px] font-mono leading-none text-muted-foreground uppercase mt-1">
                    {userRole || "..."}
                  </p>
                </div>
              </DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator className="bg-white/10" />
            <DropdownMenuItem onClick={handleLogout} className="text-destructive focus:bg-destructive/10 focus:text-destructive cursor-pointer">
              <LogOut className="mr-2 h-4 w-4" />
              <span>Sair</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
