import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { useSyncExternalStore } from "react";
import { GOOGLE_CLIENT_ID, MOCK, SUPABASE_ANON_KEY, SUPABASE_URL } from "../config";

export interface AuthSnapshot {
  ready: boolean;
  token: string | null;
  email: string | null;
}

/*
 * 구글 직접 로그인: 구글에서 이 사이트(origin + "/")로 바로 돌아오게 해 계정 선택 화면에 supabase.co 대신 이 사이트 주소가 뜨게 한다.
 * 돌아올 때 주소 # 뒤에 id_token 이 붙어 오고, 그걸 Supabase signInWithIdToken 으로 넘긴다.
 * nonce 는 구글에 해시를, Supabase 에 원문을 준다(Supabase 가 해시해 토큰 안의 값과 비교한다).
 */
const GOOGLE_STATE_KEY = "chefear.google.state";
const GOOGLE_NONCE_KEY = "chefear.google.nonce";

interface GoogleReturn {
  idToken: string | null;
  nonce: string | null;
  error: string | null;
}

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** 구글에서 돌아온 주소면 # 뒤를 꺼내고 지운다. Supabase 클라이언트가 주소를 읽기 전에 불러야 한다. */
function takeGoogleReturn(): GoogleReturn | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const state = params.get("state");
  if (!state?.startsWith("g_")) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const store = storage();
  const expected = store?.getItem(GOOGLE_STATE_KEY) ?? null;
  const nonce = store?.getItem(GOOGLE_NONCE_KEY) ?? null;
  store?.removeItem(GOOGLE_STATE_KEY);
  store?.removeItem(GOOGLE_NONCE_KEY);
  if (params.get("error")) return { idToken: null, nonce: null, error: "구글 로그인을 취소했거나 완료하지 못했어요." };
  if (state !== expected || !nonce) return { idToken: null, nonce: null, error: "로그인 확인에 실패했어요. 다시 시도해 주세요." };
  return { idToken: params.get("id_token"), nonce, error: null };
}

const googleReturn = takeGoogleReturn();
let googleError: string | null = googleReturn?.error ?? null;
let googlePending = Boolean(googleReturn?.idToken);

/** 구글에서 돌아오며 생긴 오류를 한 번만 꺼낸다(로그인 화면에 보여 줄 용도). */
export function takeGoogleError(): string | null {
  const e = googleError;
  googleError = null;
  return e;
}

function randomHex(bytes = 16): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const supabase: SupabaseClient | null =
  SUPABASE_URL && SUPABASE_ANON_KEY
    ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
      })
    : null;

/** 로그인 수단을 보여 줄 수 있는지(Supabase 설정 또는 목업). */
export const googleAvailable = MOCK || supabase !== null;
export const emailLoginAvailable = MOCK || supabase !== null;

let snapshot: AuthSnapshot = { ready: !supabase, token: null, email: null };
const listeners = new Set<() => void>();

function set(next: AuthSnapshot) {
  if (next.ready === snapshot.ready && next.token === snapshot.token && next.email === snapshot.email) return;
  snapshot = next;
  listeners.forEach((l) => l());
}

if (supabase) {
  // 구글 토큰을 넘기는 동안에는 로그인 화면이 잠깐 비치지 않게 ready 를 미룬다.
  supabase.auth
    .getSession()
    .then(({ data }) =>
      set({ ready: !googlePending, token: data.session?.access_token ?? null, email: data.session?.user.email ?? null }),
    )
    .catch(() => set({ ready: !googlePending, token: null, email: null }));
  supabase.auth.onAuthStateChange((_event, session) => {
    set({ ready: !googlePending, token: session?.access_token ?? null, email: session?.user.email ?? null });
  });
  if (googleReturn?.idToken && googleReturn.nonce) {
    supabase.auth
      .signInWithIdToken({ provider: "google", token: googleReturn.idToken, nonce: googleReturn.nonce })
      .then(({ data, error }) => {
        if (error) googleError = "구글 로그인을 마치지 못했어요. 다시 시도해 주세요.";
        googlePending = false;
        set({ ready: true, token: data.session?.access_token ?? null, email: data.session?.user.email ?? null });
      })
      .catch(() => {
        googleError = "구글 로그인을 마치지 못했어요. 다시 시도해 주세요.";
        googlePending = false;
        set({ ready: true, token: null, email: null });
      });
  }
}

export function useAuth(): AuthSnapshot {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => snapshot,
  );
}

/** API 호출용 Bearer 토큰. 없으면 익명. */
export function getAccessToken(): string | null {
  return snapshot.token;
}

function mockSignIn(email: string) {
  set({ ready: true, token: "mock-token", email });
}

export async function signInWithGoogle(): Promise<void> {
  if (MOCK) return mockSignIn("google-user@example.com");
  if (!supabase) throw new Error("로그인이 설정되지 않았어요.");
  const store = storage();
  if (GOOGLE_CLIENT_ID && store) {
    const nonce = randomHex();
    const state = "g_" + randomHex();
    store.setItem(GOOGLE_NONCE_KEY, nonce);
    store.setItem(GOOGLE_STATE_KEY, state);
    const params = new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      redirect_uri: window.location.origin + "/",
      response_type: "id_token",
      scope: "openid email profile",
      nonce: await sha256Hex(nonce),
      state,
      prompt: "select_account",
    });
    window.location.assign("https://accounts.google.com/o/oauth2/v2/auth?" + params.toString());
    return;
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.origin + window.location.pathname },
  });
  if (error) throw error;
}

export async function signInWithPassword(email: string, password: string): Promise<void> {
  if (MOCK) return mockSignIn(email || "demo@example.com");
  if (!supabase) throw new Error("로그인이 설정되지 않았어요.");
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw new Error(authMessage(error.message, "이메일 또는 비밀번호가 올바르지 않습니다."));
}

/** Supabase 가 주는 영어 오류를 화면용 한글로 바꾼다. 모르는 문구는 fallback. */
function authMessage(raw: string, fallback: string): string {
  const m = raw.toLowerCase();
  if (m.includes("email not confirmed")) return "메일 확인이 아직이에요. 받은 편지함의 확인 링크를 눌러 주세요.";
  if (m.includes("already registered") || m.includes("already been registered")) return "이미 가입된 이메일이에요. 로그인해 주세요.";
  if (m.includes("rate limit") || m.includes("too many")) return "시도가 너무 많아요. 잠시 후 다시 해 주세요.";
  if (m.includes("password") && m.includes("characters")) return "비밀번호는 8자 이상이어야 해요.";
  if (m.includes("invalid") && m.includes("email")) return "이메일 주소를 확인해 주세요.";
  if (m.includes("signups not allowed") || m.includes("signup is disabled")) return "지금은 가입을 받지 않아요.";
  return fallback;
}

/** 가입 후 곧바로 로그인되면 true, 확인 메일이 필요하면 false. */
export async function signUpWithPassword(email: string, password: string): Promise<boolean> {
  if (MOCK) {
    mockSignIn(email);
    return true;
  }
  if (!supabase) throw new Error("로그인이 설정되지 않았어요.");
  const { data, error } = await supabase.auth.signUp({ email, password });
  if (error) throw new Error(authMessage(error.message, "가입하지 못했어요. 잠시 후 다시 시도해 주세요."));
  return data.session !== null;
}

export async function signOut(): Promise<void> {
  if (MOCK || !supabase) {
    set({ ready: true, token: null, email: null });
    return;
  }
  await supabase.auth.signOut();
  set({ ready: true, token: null, email: null });
}
