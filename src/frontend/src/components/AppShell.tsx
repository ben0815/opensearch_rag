import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import ImpersonationBanner from "./ImpersonationBanner";
import { useAuthStore } from "@/stores/authStore";

export default function AppShell() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="d-flex flex-column" style={{ height: "100vh" }}>
      {user?.is_impersonation && <ImpersonationBanner />}
      <div className="d-flex flex-grow-1 overflow-hidden">
        <Sidebar />
        <main className="flex-grow-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
