import { useTranslation } from "react-i18next";

export default function ThinkingIndicator() {
  const { t } = useTranslation();
  return (
    <div className="d-flex align-items-center gap-2 text-body-secondary">
      <div className="thinking-dots">
        <span>·</span>
        <span>·</span>
        <span>·</span>
      </div>
      <small>{t("chat.thinking")}</small>
    </div>
  );
}
