"use client";

import { useAuthStore } from "@/store/useAuthStore";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { LogOut, Menu, User } from "lucide-react";
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
    <header className="flex h-[60px] items-center gap-4 border-b border-border/50 bg-card/30 backdrop-blur-md px-6 shadow-sm sticky top-0 z-30">
      <Sheet>
        <SheetTrigger className="shrink-0 md:hidden inline-flex items-center justify-center rounded-md text-sm font-medium hover:bg-accent hover:text-accent-foreground h-10 w-10">
          <Menu className="h-5 w-5" />
          <span className="sr-only">Menu de navegação</span>
        </SheetTrigger>
        <SheetContent side="left" className="flex flex-col p-0 w-64 border-r border-border/50">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          {/* We pass a prop to force it to show on mobile if needed, but the best way is to adapt Sidebar */}
          <Sidebar className="block border-none" />
        </SheetContent>
      </Sheet>

      <div className="flex-1">
        <h1 className="text-lg font-semibold tracking-tight">
          {tenant?.name || "Carregando..."}
        </h1>
      </div>

      <div className="flex items-center gap-4">
        <DropdownMenu>
          <DropdownMenuTrigger className="relative h-9 w-9 rounded-full ring-1 ring-border/50 bg-background hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring flex items-center justify-center">
            <Avatar className="h-9 w-9">
              <AvatarImage src="" alt="Avatar" />
              <AvatarFallback className="bg-primary/10 text-primary">
                <User className="h-4 w-4" />
              </AvatarFallback>
            </Avatar>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56" align="end">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col space-y-1">
                  <p className="text-sm font-medium leading-none">{userEmail || "usuário"}</p>
                  <p className="text-xs leading-none text-muted-foreground uppercase">
                    {userRole || "..."}
                  </p>
                </div>
              </DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
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
