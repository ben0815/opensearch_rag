import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { auth } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";

export default function ImpersonationBanner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, setUser } = useAuthStore();

  async function stopImpersonation() {
    await auth.logout().catch(() => {});
    // Re-authenticate as the original admin — the original session cookie is gone;
    // the user must log in again.
    setUser(null);
    navigate("/login");
  }

  if (!user) return null;

  return (
    <div className="impersonation-banner d-flex align-items-center justify-content-between">
      <span>
        <i className="bi bi-person-fill-exclamation me-2" />
        {t("admin.impersonating", {
          user: user.display_name ?? user.ldap_uid,
          admin: user.impersonated_by ?? "Admin",
        })}
      </span>
      <button className="btn btn-sm btn-warning ms-3" onClick={stopImpersonation}>
        {t("admin.stopImpersonation")}
      </button>
    </div>
  );
}
