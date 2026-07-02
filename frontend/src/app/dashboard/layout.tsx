"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/useAuthStore";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Navbar } from "@/components/dashboard/navbar";

const DASHBOARD_ROUTES = [
  "/dashboard/inbox",
  "/dashboard/calendar",
  "/dashboard/services",
  "/dashboard/team",
  "/dashboard/settings",
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { accessToken, fetchTenant } = useAuthStore();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (!accessToken) {
      router.push("/login");
    } else {
      fetchTenant();
    }
  }, [accessToken, router, fetchTenant]);

  // Prefetch all sidebar routes so first-click navigation is instant
  useEffect(() => {
    DASHBOARD_ROUTES.forEach((route) => router.prefetch(route));
  }, [router]);

  if (!mounted || !accessToken) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="h-12 w-12 rounded-full bg-primary/20"></div>
          <div className="h-4 w-32 rounded-md bg-muted"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden md:pl-[280px]">
        <Navbar />
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
