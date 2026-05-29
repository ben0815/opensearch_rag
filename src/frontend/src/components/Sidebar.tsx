import { NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { auth } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { useInstanceStore } from "@/stores/instanceStore";
import InstanceSelector from "./InstanceSelector";
import OnlineUsers from "./OnlineUsers";
import ThemeToggle from "./ThemeToggle";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
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
    <nav className={`app-sidebar d-flex flex-column bg-body-secondary p-2 gap-1${collapsed ? " collapsed" : ""}`}>

      {/* Header: logo + toggle */}
      <div className="d-flex align-items-center justify-content-between px-3 py-2 mb-1">
        {!collapsed && <span className="fw-bold fs-5">RAG</span>}
        <button
          className="btn btn-sm btn-link p-0 text-body ms-auto"
          onClick={onToggle}
          title={collapsed ? t("nav.expand") : t("nav.collapse")}
          style={{ lineHeight: 1 }}
        >
          <i className={`bi bi-chevron-${collapsed ? "right" : "left"}`} />
        </button>
      </div>

      {/* Instance selector — hidden when collapsed */}
      {!collapsed && <InstanceSelector />}
      {collapsed && selectedInstance && (
        <div
          className="px-3 py-2 text-body-secondary text-center"
          title={selectedInstance.name}
          style={{ fontSize: "0.7rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          <i className="bi bi-collection" />
        </div>
      )}

      <NavLink to="/chat" className={navClass} title={collapsed ? t("chat.title") : undefined}>
        <i className="bi bi-chat-dots flex-shrink-0" />
        <span className="sidebar-label">{t("chat.title")}</span>
      </NavLink>

      {selectedInstance && (selectedInstance.role === "manager" || user?.is_global_admin) && (
        <NavLink to="/documents" className={navClass} title={collapsed ? t("documents.title") : undefined}>
          <i className="bi bi-file-earmark-text flex-shrink-0" />
          <span className="sidebar-label">{t("documents.title")}</span>
        </NavLink>
      )}

      <NavLink to="/history" className={navClass} title={collapsed ? t("history.title") : undefined}>
        <i className="bi bi-clock-history flex-shrink-0" />
        <span className="sidebar-label">{t("history.title")}</span>
      </NavLink>

      {user?.is_global_admin && (
        <NavLink to="/admin" className={navClass} title={collapsed ? t("admin.title") : undefined}>
          <i className="bi bi-gear flex-shrink-0" />
          <span className="sidebar-label">{t("admin.title")}</span>
        </NavLink>
      )}

      <hr className="my-1 mx-2" style={{ borderColor: "var(--bs-border-color)", opacity: 1 }} />
      <OnlineUsers collapsed={collapsed} />

      <div className="mt-auto d-flex flex-column gap-1">
        <ThemeToggle collapsed={collapsed} />
        {!collapsed && (
          <div className="px-3 py-2 text-body-secondary small text-truncate">
            {user?.display_name ?? user?.ldap_uid}
          </div>
        )}
        <button
          className="nav-link d-flex align-items-center gap-2 px-3 py-2 rounded text-body btn btn-link text-start"
          onClick={handleLogout}
          title={collapsed ? t("auth.logout") : undefined}
        >
          <i className="bi bi-box-arrow-left flex-shrink-0" />
          <span className="sidebar-label">{t("auth.logout")}</span>
        </button>
      </div>
    </nav>
  );
}
