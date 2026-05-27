import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  label?: string;
}

export default function ThinkingIndicator({ label }: Props) {
  const { t } = useTranslation();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - start) / 1000), 100);
    return () => clearInterval(id);
  }, []);

  const timeStr =
    elapsed < 60
      ? `${elapsed.toFixed(1)} s`
      : `${Math.floor(elapsed / 60)} min ${Math.round(elapsed % 60)} s`;

  return (
    <div className="d-flex align-items-center gap-2 text-body-secondary">
      <div className="thinking-dots">
        <span>·</span>
        <span>·</span>
        <span>·</span>
      </div>
      <small>{label ?? t("chat.thinking")}</small>
      <small className="text-nowrap">
        <i className="bi bi-stopwatch me-1" />
        {timeStr}
      </small>
    </div>
  );
}
