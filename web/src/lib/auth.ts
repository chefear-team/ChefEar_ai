import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { useSyncExternalStore } from "react";
import { MOCK, SUPABASE_ANON_KEY, SUPABASE_URL } from "../config";

export interface AuthSnapshot {
  ready: boolean;
  token: string | null;
  email: string | null;
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
  supabase.auth
    .getSession()
    .then(({ data }) =>
      set({ ready: true, token: data.session?.access_token ?? null, email: data.session?.user.email ?? null }),
    )
    .catch(() => set({ ready: true, token: null, email: null }));
  supabase.auth.onAuthStateChange((_event, session) => {
    set({ ready: true, token: session?.access_token ?? null, email: session?.user.email ?? null });
  });
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
