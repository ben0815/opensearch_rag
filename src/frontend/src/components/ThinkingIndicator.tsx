import { useTranslation } from "react-i18next";

interface Props {
  label?: string;
}

export default function ThinkingIndicator({ label }: Props) {
  const { t } = useTranslation();
  return (
    <div className="d-flex align-items-center gap-2 text-body-secondary">
      <div className="thinking-dots">
        <span>·</span>
        <span>·</span>
        <span>·</span>
      </div>
      <small>{label ?? t("chat.thinking")}</small>
    </div>
  );
}
