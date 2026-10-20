import { useEffect, useState } from "react";
import { playProcessingChime } from "../lib/chime";

/** 이 시간(ms)보다 오래 걸릴 때만 보여 준다. 빨리 끝나는 요청에는 화면이 깜빡이지 않게. */
const SHOW_AFTER_MS = 400;

/**
 * 말을 보낸 뒤 처리가 길어지면 화면 전체에 "말씀 잘 들었어요, 잠시만요..."를 띄우고 알림음을 한 번 울린다.
 * 서버 응답이 오면 사라진다. 글자 입력·버튼 요청에는 쓰지 않는다(그때는 화면만 흐려진다).
 */
export function ProcessingOverlay({ active }: { active: boolean }) {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setShown(true);
      playProcessingChime();
    }, SHOW_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [active]);

  if (!active || !shown) return null;
  return (
    <div className="overlay" role="status" aria-live="polite">
      <div className="overlay-card">
        <span className="spinner big" aria-hidden="true" />
        <strong>말씀 잘 들었어요, 잠시만요...</strong>
      </div>
    </div>
  );
}
