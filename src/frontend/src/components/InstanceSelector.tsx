import { useTranslation } from "react-i18next";
import { Dropdown } from "react-bootstrap";
import { useInstanceStore } from "@/stores/instanceStore";
import { user as userApi } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";

export default function InstanceSelector() {
  const { t } = useTranslation();
  const { instances, selectedId, setSelectedId } = useInstanceStore();
  const authUser = useAuthStore((s) => s.user);
  const selected = instances.find((i) => i.id === selectedId);

  async function handleSelect(id: number) {
    setSelectedId(id);
    // Persist as user default preference
    await userApi.patchMe({ default_instance_id: id }).catch(() => {});
    // Update auth store with new default
    if (authUser) {
      useAuthStore.getState().setUser({ ...authUser, default_instance_id: id });
    }
  }

  if (instances.length === 0) {
    return (
      <div className="px-3 py-2 text-body-secondary small">{t("chat.noInstances")}</div>
    );
  }

  return (
    <Dropdown className="mb-2">
      <Dropdown.Toggle
        variant="outline-secondary"
        size="sm"
        className="w-100 text-start d-flex align-items-center justify-content-between"
      >
        <span className="text-truncate">
          <i className="bi bi-collection me-2" />
          {selected?.name ?? t("instances.select")}
        </span>
      </Dropdown.Toggle>
      <Dropdown.Menu className="w-100">
        {instances.map((inst) => (
          <Dropdown.Item
            key={inst.id}
            active={inst.id === selectedId}
            onClick={() => handleSelect(inst.id)}
          >
            <span>{inst.name}</span>
            <span className="ms-2 badge bg-secondary-subtle text-secondary small">
              {inst.role}
            </span>
          </Dropdown.Item>
        ))}
      </Dropdown.Menu>
    </Dropdown>
  );
}
