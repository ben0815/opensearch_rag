import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { presence } from "@/api/client";
import type { UserPresenceOut } from "@/types/api";

interface OnlineUsersProps {
  collapsed: boolean;
}

const MAX_VISIBLE = 8;

function initials(user: UserPresenceOut): string {
  const name = user.display_name?.trim() || user.ldap_uid;
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

export default function OnlineUsers({ collapsed }: OnlineUsersProps) {
  const { t } = useTranslation();
  const [users, setUsers] = useState<UserPresenceOut[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    let intervalId: ReturnType<typeof setInterval>;

    const load = () => {
      presence
        .list(controller.signal)
        .then(setUsers)
        .catch(() => {});
    };

    load();
    intervalId = setInterval(load, 30_000);

    return () => {
      clearInterval(intervalId);
      controller.abort();
    };
  }, []);

  if (users.length === 0) return null;

  const visible = users.slice(0, MAX_VISIBLE);
  const hidden = users.length - visible.length;

  if (collapsed) {
    return (
      <div className="d-flex flex-column align-items-center gap-1 px-1 py-2">
        {visible.map((u) => (
          <div
            key={u.id}
            title={`${u.display_name ?? u.ldap_uid}${u.is_querying ? ` — ${t("presence.querying")}` : ""}`}
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "0.65rem",
              fontWeight: 700,
              flexShrink: 0,
              background: "var(--bs-secondary-bg)",
              border: `2px solid ${u.is_querying ? "var(--bs-primary)" : "var(--bs-success)"}`,
              color: "var(--bs-body-color)",
            }}
          >
            {initials(u)}
          </div>
        ))}
        {hidden > 0 && (
          <div
            title={`+${hidden}`}
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "0.6rem",
              background: "var(--bs-secondary-bg)",
              border: "2px solid var(--bs-border-color)",
              color: "var(--bs-secondary-color)",
            }}
          >
            +{hidden}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="px-2 py-1">
      <div className="text-body-secondary small px-1 mb-1" style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {t("presence.title")} ({users.length})
      </div>
      <div style={{ maxHeight: 200, overflowY: "auto" }}>
        {visible.map((u) => (
          <div
            key={u.id}
            className="d-flex align-items-center gap-2 px-1 py-1 rounded"
            title={u.is_querying ? t("presence.querying") : t("presence.online")}
            style={{ fontSize: "0.82rem" }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                flexShrink: 0,
                background: u.is_querying ? "var(--bs-primary)" : "var(--bs-success)",
                animation: u.is_querying ? "presence-pulse 1.4s ease-in-out infinite" : undefined,
              }}
            />
            <span className="text-truncate text-body">
              {u.display_name ?? u.ldap_uid}
            </span>
          </div>
        ))}
        {hidden > 0 && (
          <div className="px-1 text-body-secondary" style={{ fontSize: "0.75rem" }}>
            {t("presence.more", { count: hidden })}
          </div>
        )}
      </div>
    </div>
  );
}
