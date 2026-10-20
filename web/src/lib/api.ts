import { API_BASE, MOCK, REQUEST_TIMEOUT_MS, TTS_TIMEOUT_MS } from "../config";
import type { Action, Api, MyRecipeDetail, MyRecipeInput, MyRecipeSummary } from "../types";
import { getAccessToken } from "./auth";
import { ApiError, friendlyServerMessage } from "./errors";
import { mockApi } from "./mockApi";

// ---- 느린 요청 모니터(콜드 스타트 안내용) ----
// warmup 은 일부러 제외한다. 추론 컨테이너를 깨우느라 오래 걸려도 API 는 이미 떠 있을 수 있다.
const inflight = new Map<number, number>();
let nextId = 1;
let hadSuccess = false;
const monitorListeners = new Set<() => void>();
const notifyMonitor = () => monitorListeners.forEach((l) => l());

export function subscribeMonitor(cb: () => void): () => void {
  monitorListeners.add(cb);
  return () => monitorListeners.delete(cb);
}

/** 가장 오래 걸리고 있는 요청의 경과 ms (없으면 0), 그리고 아직 한 번도 성공 못 했는지. */
export function readMonitor(): { oldestMs: number; pending: number; cold: boolean } {
  let oldest = 0;
  const now = Date.now();
  inflight.forEach((t) => {
    oldest = Math.max(oldest, now - t);
  });
  return { oldestMs: oldest, pending: inflight.size, cold: !hadSuccess };
}

async function request(
  path: string,
  init: RequestInit,
  opts: { timeout?: number; track?: boolean } = {},
): Promise<Response> {
  const { timeout = REQUEST_TIMEOUT_MS, track = true } = opts;
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeout);
  const id = nextId++;
  if (track) {
    inflight.set(id, Date.now());
    notifyMonitor();
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: ctrl.signal });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.clone().json();
        detail = typeof body?.detail === "string" ? body.detail : "";
      } catch {
        /* 본문이 JSON 이 아니면 무시 */
      }
      throw new ApiError(res.status, friendlyServerMessage(detail) ?? (detail || `요청에 실패했어요 (${res.status})`));
    }
    if (track) hadSuccess = true;
    return res;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") throw new ApiError(0, "서버 응답이 너무 늦어요.");
    throw new ApiError(0, "서버에 연결하지 못했어요.");
  } finally {
    window.clearTimeout(timer);
    if (track) {
      inflight.delete(id);
      notifyMonitor();
    }
  }
}

const json = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const enc = encodeURIComponent;

const realApi: Api = {
  async warmup() {
    await request("/api/warmup", { method: "POST" }, { track: false }).catch(() => undefined);
  },
  async createSession() {
    return (await request("/api/session", { method: "POST" })).json();
  },
  async getSession(id) {
    return (await request(`/api/session/${enc(id)}`, { method: "GET" })).json();
  },
  async utteranceText(id, text) {
    return (await request(`/api/session/${enc(id)}/utterance`, json({ text }))).json();
  },
  async utteranceAudio(id, wav) {
    const form = new FormData();
    form.append("audio", wav, "utterance.wav");
    return (await request(`/api/session/${enc(id)}/utterance`, { method: "POST", body: form })).json();
  },
  async action(id, action: Action) {
    return (await request(`/api/session/${enc(id)}/action`, json(action))).json();
  },
  async tts(text) {
    const res = await request("/api/tts", json({ text }), { timeout: TTS_TIMEOUT_MS, track: false });
    return res.blob();
  },
  async listMyRecipes() {
    return (await request("/api/my-recipes", { method: "GET" })).json() as Promise<MyRecipeSummary[]>;
  },
  async getMyRecipe(id) {
    return (await request(`/api/my-recipes/${enc(id)}`, { method: "GET" })).json() as Promise<MyRecipeDetail>;
  },
  async updateMyRecipe(id, body: MyRecipeInput) {
    return (await request(`/api/my-recipes/${enc(id)}`, json(body, "PUT"))).json() as Promise<MyRecipeDetail>;
  },
  async deleteMyRecipe(id) {
    await request(`/api/my-recipes/${enc(id)}`, { method: "DELETE" });
  },
};

export const api: Api = MOCK ? mockApi : realApi;
