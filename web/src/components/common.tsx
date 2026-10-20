import { useEffect, useState } from "react";
import { SLOW_AFTER_MS } from "../config";
import { readMonitor, subscribeMonitor } from "../lib/api";
import type { ChatMessage } from "../types";

/** 원본 ui/theme.py 의 인라인 SVG 아이콘을 그대로 옮겼다(이모지는 OS마다 달라 보여서 쓰지 않는다). */
const ICONS = {
  mic: '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>',
  speaker: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
  check: '<circle cx="12" cy="12" r="10"/><polyline points="8 12.5 11 15.5 16 9"/>',
  x: '<circle cx="12" cy="12" r="10"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>',
  question:
    '<circle cx="12" cy="12" r="10"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.3 1-1.3 1.9"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  sparkle: '<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>',
  basket:
    '<path d="M3 11h18M12 3v3M7 5v1M17 5v1"/><path d="M4 11l1.2 8.4A2 2 0 0 0 7.2 21h9.6a2 2 0 0 0 2-1.6L20 11"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  inbox: '<path d="M3 13l3-8h12l3 8"/><path d="M3 13v6h18v-6h-5l-1 2h-6l-1-2H3Z"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12Z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff:
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  );
}

export function PlayIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <polygon points="6 3 20 12 6 21 6 3" />
    </svg>
  );
}

export function Chips({ items, label }: { items: string[]; label?: string }) {
  if (items.length === 0) return null;
  return (
    <section className="block" aria-label={label}>
      {label && (
        <h3 className="block-title">
          <Icon name="basket" size={16} />
          {label}
        </h3>
      )}
      <ul className="chips">
        {items.map((it, i) => (
          <li className="chip" key={`${it}-${i}`}>
            {it}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 원본의 "나: / ChefEar:" 대화 카드. */
export function Chat({ messages }: { messages: ChatMessage[] }) {
  const recent = messages.slice(-4);
  if (recent.length === 0) return null;
  return (
    <section className="block" aria-label="최근 대화">
      <ul className="chat">
        {recent.map((m, i) => (
          <li key={i} className="chat-row">
            <span className={`avatar ${m.role}`}>
              <Icon name={m.role === "user" ? "mic" : "speaker"} size={m.role === "user" ? 16 : 15} />
            </span>
            <p>
              <span className={`who ${m.role}`}>{m.role === "user" ? "나:" : "ChefEar:"}</span>
              {m.text}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

/** 중앙 안내. icon 이 있으면 원본처럼 색 원 안에 SVG 를 그린다. mic 은 숨쉬는 큰 마이크. */
export function Hero({
  icon,
  tone,
  title,
  children,
}: {
  icon?: IconName;
  tone?: "positive" | "warn" | "neutral";
  title: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="hero">
      {icon === "mic" ? (
        <div className="big-mic" aria-hidden="true">
          <Icon name="mic" size={34} />
        </div>
      ) : (
        icon && (
          <div className={`lead-icon ${tone ?? "neutral"}`} aria-hidden="true">
            <Icon name={icon} size={26} />
          </div>
        )
      )}
      <h1>{title}</h1>
      {children}
    </div>
  );
}

/** 요청이 2초 넘게 걸리면 안내를 띄운다. 첫 요청이면 콜드 스타트 문구, 이후에는 짧은 처리 중 문구. */
export function SlowBanner() {
  const [snap, setSnap] = useState(readMonitor());
  useEffect(() => {
    const tick = () => setSnap(readMonitor());
    const unsub = subscribeMonitor(tick);
    const timer = window.setInterval(tick, 500);
    return () => {
      unsub();
      window.clearInterval(timer);
    };
  }, []);

  if (snap.pending === 0 || snap.oldestMs < SLOW_AFTER_MS) return null;
  const seconds = Math.floor(snap.oldestMs / 1000);
  return (
    <div className="slow-banner" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {snap.cold ? (
        <span>서버를 깨우는 중이에요 (처음 접속 시 수십 초 걸릴 수 있어요) · {seconds}초</span>
      ) : (
        <span>처리하는 중이에요 · {seconds}초</span>
      )}
    </div>
  );
}
