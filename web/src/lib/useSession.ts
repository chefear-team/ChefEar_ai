import { useCallback, useRef, useState } from "react";
import type { Action, Speech, State } from "../types";
import { api } from "./api";
import { errorMessage, errorStatus } from "./errors";

const SID_KEY = "chefear.session_id";

function readSid(): string | null {
  try {
    return window.localStorage.getItem(SID_KEY);
  } catch {
    return null;
  }
}

function writeSid(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(SID_KEY, id);
    else window.localStorage.removeItem(SID_KEY);
  } catch {
    /* 저장 못 해도 이 탭에서는 계속 동작한다 */
  }
}

interface Options {
  /** 새 State 가 도착했을 때 읽어 줄 문장(없으면 null). 시작하기 전에는 호출되지 않는다. */
  onSpeech: (speech: Speech | null) => void;
}

/**
 * 서버 State 를 그대로 보여 주는 얇은 훅. 클라이언트가 들고 있는 것은 session_id 뿐이다.
 * 모든 요청은 순서대로(직렬) 보내서 응답이 뒤섞이지 않게 한다.
 */
export function useSession({ onSpeech }: Options) {
  const [state, setState] = useState<State | null>(null);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const sidRef = useRef<string | null>(readSid());
  const chainRef = useRef<Promise<void>>(Promise.resolve());
  const speakEnabledRef = useRef(false);
  const lastSpeechRef = useRef<Speech | null>(null);
  const onSpeechRef = useRef(onSpeech);
  onSpeechRef.current = onSpeech;

  const apply = useCallback((s: State, speak: boolean) => {
    sidRef.current = s.session_id;
    writeSid(s.session_id);
    setState(s);
    if (s.speech) lastSpeechRef.current = s.speech;
    if (speak && speakEnabledRef.current) onSpeechRef.current(s.speech);
  }, []);

  /** 직렬 큐에 요청을 넣는다. fn 은 세션 id 를 받아 State 를 돌려준다. */
  const run = useCallback(
    (fn: (id: string) => Promise<State>, opts: { speak?: boolean } = {}): Promise<void> => {
      const { speak = true } = opts;
      setPending((p) => p + 1);
      const job = chainRef.current.then(async () => {
        try {
          const id = sidRef.current;
          if (!id) {
            const created = await api.createSession();
            apply(created, speak);
            return; // 새 세션을 만든 경우 원래 요청은 의미가 없다
          }
          try {
            apply(await fn(id), speak);
          } catch (e) {
            if (errorStatus(e) !== 404) throw e;
            // 서버가 세션을 잃었다(재시작 등). 새로 시작한다.
            const created = await api.createSession();
            apply({ ...created, notice: "세션이 만료되어 처음부터 다시 시작해요." }, speak);
          }
          setError(null);
        } catch (e) {
          setError(errorMessage(e, "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."));
        }
      });
      chainRef.current = job.then(
        () => undefined,
        () => undefined,
      );
      return job.finally(() => setPending((p) => p - 1));
    },
    [apply],
  );

  /** 첫 로드: 저장된 세션이 있으면 이어서, 없거나 실패하면 새로 만든다. 읽어 주지는 않는다. */
  const init = useCallback(() => {
    const saved = sidRef.current;
    return run(
      async () => {
        if (saved) {
          try {
            return await api.getSession(saved);
          } catch (e) {
            if (errorStatus(e) !== 404) throw e;
          }
        }
        return api.createSession();
      },
      { speak: true }, // 시작하기 전이면 apply 안에서 걸러지고, 시작한 뒤에 도착했으면 인사말을 읽는다
    );
  }, [run]);

  const act = useCallback(
    (action: Action) => run((id) => api.action(id, action)),
    [run],
  );
  const sayText = useCallback((text: string) => run((id) => api.utteranceText(id, text)), [run]);
  const sendAudio = useCallback((wav: Blob) => run((id) => api.utteranceAudio(id, wav)), [run]);
  /** 로그인/로그아웃 뒤 logged_in 같은 값을 다시 받아 온다. */
  const refresh = useCallback(() => run((id) => api.getSession(id), { speak: false }), [run]);

  /** "시작하기"를 누른 뒤부터 읽어 주기 시작하고, 지금 화면의 안내를 한 번 읽는다. */
  const enableSpeech = useCallback(() => {
    speakEnabledRef.current = true;
    onSpeechRef.current(lastSpeechRef.current);
  }, []);
  const replay = useCallback(() => {
    onSpeechRef.current(lastSpeechRef.current);
  }, []);
  const dismissError = useCallback(() => setError(null), []);

  /** 로그아웃: 이 사용자의 세션을 버린다. 다음 사용자가 이전 사용자의 화면을 보지 않게 한다. */
  const reset = useCallback(() => {
    sidRef.current = null;
    writeSid(null);
    lastSpeechRef.current = null;
    speakEnabledRef.current = false;
    setState(null);
    setError(null);
  }, []);

  // 서비스 전체가 로그인 전용이라 세션은 로그인한 뒤에 만든다(App 이 init 을 부른다).
  return { state, busy: pending > 0, error, dismissError, act, sayText, sendAudio, refresh, init, reset, enableSpeech, replay };
}
