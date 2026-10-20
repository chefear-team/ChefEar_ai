const env = import.meta.env;
const clean = (v: string | undefined) => (v ?? "").trim();

export const MOCK = clean(env.VITE_MOCK) === "1";
export const API_BASE = clean(env.VITE_API_BASE).replace(/\/+$/, "");
export const SUPABASE_URL = clean(env.VITE_SUPABASE_URL);
export const SUPABASE_ANON_KEY = clean(env.VITE_SUPABASE_ANON_KEY);
export const DEMO_VIDEO_URL = clean(env.VITE_DEMO_VIDEO_URL);
/** 구글 OAuth 클라이언트 ID(공개 값). 있으면 구글에서 이 사이트로 바로 돌아와 계정 선택 화면에 이 사이트 주소가 뜬다. */
export const GOOGLE_CLIENT_ID = clean(env.VITE_GOOGLE_CLIENT_ID);

/** 서버 요청 제한 시간. 콜드 스타트에 수십 초 걸릴 수 있어 넉넉하게 잡는다. */
export const REQUEST_TIMEOUT_MS = 120_000;
export const TTS_TIMEOUT_MS = 45_000;
/** 이 시간보다 오래 걸리는 첫 요청이면 "서버를 깨우는 중" 안내를 띄운다. */
export const SLOW_AFTER_MS = 2_000;
/** 음성 재생이 끝난 뒤 마이크를 다시 듣기 시작하기까지 기다리는 시간. */
export const VAD_COOLDOWN_MS = 600;
