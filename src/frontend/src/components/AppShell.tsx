import { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import ImpersonationBanner from "./ImpersonationBanner";
import { useAuthStore } from "@/stores/authStore";

export default function AppShell() {
  const user = useAuthStore((s) => s.user);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true",
  );

  function toggleSidebar() {
    setCollapsed((v) => {
      localStorage.setItem("sidebar-collapsed", String(!v));
      return !v;
    });
  }

  return (
    <div className="d-flex flex-column" style={{ height: "100vh" }}>
      {user?.is_impersonation && <ImpersonationBanner />}
      <div className="d-flex flex-grow-1 overflow-hidden">
        <Sidebar collapsed={collapsed} onToggle={toggleSidebar} />
        <main className="flex-grow-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
