import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

const NAV = [
  { to: "status", icon: "bi-heart-pulse", key: "admin.status" },
  { to: "users", icon: "bi-people", key: "admin.users" },
  { to: "groups", icon: "bi-diagram-3", key: "admin.groups" },
  { to: "instances", icon: "bi-collection", key: "admin.instances" },
  { to: "settings", icon: "bi-sliders", key: "admin.settings" },
  { to: "ldap", icon: "bi-shield-lock", key: "admin.ldap" },
  { to: "audit", icon: "bi-list-check", key: "admin.audit" },
  { to: "maintenance", icon: "bi-tools", key: "admin.maintenance" },
] as const;

export default function AdminLayout() {
  const { t } = useTranslation();

  return (
    <div className="d-flex h-100">
      <nav
        className="d-flex flex-column bg-body-secondary border-end p-2 gap-1"
        style={{ minWidth: 200 }}
      >
        <div className="px-3 py-2 fw-semibold text-body-secondary small text-uppercase">
          {t("admin.title")}
        </div>
        {NAV.map(({ to, icon, key }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `nav-link d-flex align-items-center gap-2 px-3 py-2 rounded ${isActive ? "active bg-primary text-white" : "text-body"}`
            }
          >
            <i className={`bi ${icon}`} />
            {t(key)}
          </NavLink>
        ))}
      </nav>
      <div className="flex-grow-1 overflow-auto p-4">
        <Outlet />
      </div>
    </div>
  );
}
