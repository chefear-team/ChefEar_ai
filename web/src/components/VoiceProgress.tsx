import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Icon } from "./common";

/** 등록·수정한 레시피의 음성 파일을 만드는 데 걸리는 시간 안내. 실측 전의 추정이라 범위로만 말한다. */
export const VOICE_ETA = "보통 1~3분";

const POLL_MS = 6000;
const GIVE_UP_S = 600;
const SLOW_S = 180;

type Phase = "preparing" | "ready" | "unknown";

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/**
 * 레시피 저장 직후 음성 파일 준비 상태를 보여 준다. 마이레시피 목록의 audio_ready 를 주기적으로 읽어
 * 끝나면 "준비 완료"로 바뀐다. 이 화면을 떠나도 서버에서는 계속 만들어지고, 마이레시피에서 같은 상태를 볼 수 있다.
 */
export function VoiceProgress({ recipeId }: { recipeId: string }) {
  const [phase, setPhase] = useState<Phase>("preparing");
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const started = Date.now();
    let failures = 0;

    const clock = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);

    const poll = async () => {
      try {
        const rows = await api.listMyRecipes();
        if (!alive) return;
        failures = 0;
        if (rows.find((r) => r.recipe_id === recipeId)?.audio_ready) {
          setPhase("ready");
          return;
        }
      } catch {
        failures += 1;
        if (alive && failures >= 3) {
          setPhase("unknown");
          return;
        }
      }
      if ((Date.now() - started) / 1000 > GIVE_UP_S) {
        if (alive) setPhase("unknown");
        return;
      }
      timer = window.setTimeout(() => void poll(), POLL_MS);
    };
    timer = window.setTimeout(() => void poll(), POLL_MS);

    return () => {
      alive = false;
      window.clearInterval(clock);
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [recipeId]);

  if (phase === "ready") {
    return (
      <div className="voiceprog ready" role="status" aria-live="polite">
        <span className="voiceprog-icon">
          <Icon name="check" size={22} />
        </span>
        <div>
          <strong>음성 준비가 끝났어요</strong>
          <p>이제 이 레시피를 말로 안내받을 수 있어요.</p>
        </div>
      </div>
    );
  }

  if (phase === "unknown") {
    return (
      <div className="voiceprog" role="status" aria-live="polite">
        <span className="voiceprog-icon">
          <Icon name="question" size={22} />
        </span>
        <div>
          <strong>준비 상태를 아직 확인하지 못했어요</strong>
          <p>음성은 서버에서 계속 만들어지고 있어요. 잠시 뒤 마이레시피에서 상태를 확인해 주세요.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="voiceprog" role="status" aria-live="polite">
      <span className="spinner big" aria-hidden="true" />
      <div>
        <strong>음성 파일을 만드는 중이에요</strong>
        <p>
          {VOICE_ETA} 걸려요 · 경과 {mmss(elapsed)}
          {elapsed > SLOW_S ? " · 평소보다 오래 걸리고 있어요. 서버를 깨우는 중일 수 있어요." : ""}
        </p>
        <p className="voiceprog-note">그동안 다른 걸 해도 돼요. 끝나면 이 레시피를 말로 안내받을 수 있어요.</p>
        <div className="indet" aria-hidden="true" />
      </div>
    </div>
  );
}
