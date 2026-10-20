import { useState, type FormEvent } from "react";
import type { VoicePhase } from "../lib/useVoice";
import { Icon } from "./common";

interface MicProps {
  phase: VoicePhase;
  error: string | null;
  muted: boolean;
  hearing: boolean;
  listening: boolean;
  speaking: boolean;
  blocked: boolean;
  processing: boolean;
  voiceScreen: boolean;
  hint: string;
  onToggleMute: () => void;
  onRetry: () => void;
  onReplay: () => void;
}

function micLabel(p: MicProps): { text: string; tone: "on" | "busy" | "off" | "error" } {
  if (p.phase === "error") return { text: "마이크를 쓸 수 없어요", tone: "error" };
  if (p.muted) return { text: "마이크가 꺼져 있어요", tone: "off" };
  if (!p.voiceScreen) return { text: "마이크가 꺼져 있어요", tone: "off" }; // 글자로 입력하는 화면
  if (p.phase === "loading" || p.phase === "off") return { text: "마이크 연결 중...", tone: "busy" };
  if (p.speaking) return { text: "읽어드리는 중", tone: "busy" };
  if (p.processing) return { text: "처리하는 중...", tone: "busy" };
  if (p.hearing) return { text: "말씀하시는 중", tone: "on" };
  if (p.listening) return { text: "듣는 중", tone: "on" };
  return { text: "잠시 쉬는 중", tone: "busy" };
}

export function MicBar(p: MicProps) {
  const { text, tone } = micLabel(p);
  return (
    <div className={`micbar ${tone}`} role="status" aria-live="polite">
      <div className="mic-orb" aria-hidden="true">
        <Icon name="mic" size={22} />
      </div>
      <div className="mic-text">
        <strong>{text}</strong>
        <span className="mic-hint">
          {p.phase === "error" && p.error ? p.error : p.muted
            ? "“마이크 켜기”를 누르면 다시 연결돼요"
            : !p.voiceScreen
              ? "이 화면에서는 글자로 입력해 주세요"
              : p.hint}
        </span>
        {p.blocked && <span className="mic-hint warn">브라우저가 소리를 막았어요. 화면을 한 번 누르고 &quot;다시 듣기&quot;를 눌러 주세요.</span>}
      </div>
      <div className="mic-actions">
        <button type="button" className="btn small" onClick={p.onReplay}>
          다시 듣기
        </button>
        {!p.voiceScreen ? null : p.phase === "error" ? (
          <button type="button" className="btn small" onClick={p.onRetry}>
            마이크 다시 연결
          </button>
        ) : (
          <button
            type="button"
            className="btn small"
            onClick={p.onToggleMute}
            aria-pressed={p.muted}
            disabled={p.phase === "loading"}
          >
            {p.muted ? "마이크 켜기" : "마이크 끄기"}
          </button>
        )}
      </div>
    </div>
  );
}

export function TextFallback({ onSend, disabled }: { onSend: (text: string) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText("");
  };
  return (
    <form className="textfallback" onSubmit={submit}>
      <label htmlFor="say-input">말 대신 입력하기</label>
      <div className="row">
        <input
          id="say-input"
          type="text"
          maxLength={200}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="예: 된장찌개 어떻게 만들어?  /  다음"
          autoComplete="off"
          enterKeyHint="send"
          disabled={disabled}
        />
        <button type="submit" className="btn primary" disabled={disabled || !text.trim()}>
          보내기
        </button>
      </div>
    </form>
  );
}
