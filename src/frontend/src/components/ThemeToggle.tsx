import { usePreferencesStore } from "@/stores/preferencesStore";
import { Dropdown } from "react-bootstrap";
import { useTranslation } from "react-i18next";

const THEMES = [
  { value: "auto", label: "Auto", icon: "bi-circle-half" },
  { value: "light", label: "Hell", icon: "bi-sun" },
  { value: "dark", label: "Dunkel", icon: "bi-moon-stars" },
] as const;

export default function ThemeToggle() {
  const { theme, setTheme } = usePreferencesStore();
  const { i18n } = useTranslation();
  const current = THEMES.find((t) => t.value === theme) ?? THEMES[0];

  return (
    <Dropdown>
      <Dropdown.Toggle
        variant="link"
        size="sm"
        className="nav-link d-flex align-items-center gap-2 px-3 py-2 text-body"
      >
        <i className={`bi ${current.icon}`} />
        <span className="small">{current.label}</span>
      </Dropdown.Toggle>
      <Dropdown.Menu>
        {THEMES.map((t) => (
          <Dropdown.Item
            key={t.value}
            active={t.value === theme}
            onClick={() => setTheme(t.value)}
          >
            <i className={`bi ${t.icon} me-2`} />
            {t.label}
          </Dropdown.Item>
        ))}
        <Dropdown.Divider />
        {(["de", "en"] as const).map((lang) => (
          <Dropdown.Item
            key={lang}
            active={i18n.language === lang}
            onClick={() => i18n.changeLanguage(lang)}
          >
            {lang === "de" ? "Deutsch" : "English"}
          </Dropdown.Item>
        ))}
      </Dropdown.Menu>
    </Dropdown>
  );
}
