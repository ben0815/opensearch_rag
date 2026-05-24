import { NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { auth } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { useInstanceStore } from "@/stores/instanceStore";
import InstanceSelector from "./InstanceSelector";
import ThemeToggle from "./ThemeToggle";

export default function Sidebar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, clear } = useAuthStore();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `nav-link d-flex align-items-center gap-2 px-3 py-2 rounded ${isActive ? "active bg-primary text-white" : "text-body"}`;

  async function handleLogout() {
    await auth.logout().catch(() => {});
    clear();
    navigate("/login");
  }

  return (
    <nav className="app-sidebar d-flex flex-column bg-body-secondary p-2 gap-1">
      <div className="px-3 py-2 mb-1">
        <span className="fw-bold fs-5">RAG</span>
      </div>

      <InstanceSelector />

      <NavLink to="/chat" className={navClass}>
        <i className="bi bi-chat-dots" />
        {t("chat.title")}
      </NavLink>

      {selectedInstance && (selectedInstance.role === "manager" || user?.is_global_admin) && (
        <NavLink to="/documents" className={navClass}>
          <i className="bi bi-file-earmark-text" />
          {t("documents.title")}
        </NavLink>
      )}

      <NavLink to="/history" className={navClass}>
        <i className="bi bi-clock-history" />
        {t("history.title")}
      </NavLink>

      {user?.is_global_admin && (
        <NavLink to="/admin" className={navClass}>
          <i className="bi bi-gear" />
          {t("admin.title")}
        </NavLink>
      )}

      <div className="mt-auto d-flex flex-column gap-1">
        <ThemeToggle />
        <div className="px-3 py-2 text-body-secondary small">
          {user?.display_name ?? user?.ldap_uid}
        </div>
        <button
          className="nav-link d-flex align-items-center gap-2 px-3 py-2 rounded text-body btn btn-link text-start"
          onClick={handleLogout}
        >
          <i className="bi bi-box-arrow-left" />
          {t("auth.logout")}
        </button>
      </div>
    </nav>
  );
}
