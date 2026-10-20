import { useSyncExternalStore } from "react";
import { MOCK, VAD_COOLDOWN_MS } from "../config";
import type { Speech } from "../types";
import { api } from "./api";
import { encodeWav } from "./wav";

export interface PlayerSnapshot {
  /** 지금 소리가 나거나 나오기를 기다리는 중 */
  speaking: boolean;
  /** speaking + 끝난 뒤 VAD_COOLDOWN_MS. 마이크는 busy 동안 멈춘다. */
  busy: boolean;
  /** 브라우저가 자동 재생을 막았다 */
  blocked: boolean;
}

const TTS_CACHE_MAX = 30;

/**
 * 음성 재생기. 재생 순서:
 *  1) speech.audio_url 이 있으면 그것을 재생
 *  2) 없거나 실패하면 POST /api/tts 로 받은 audio/mpeg 재생
 *  3) 그것도 실패하면 소리 없이 끝낸다(문장은 화면에 이미 보인다)
 * 새 speak()/stop() 이 오면 진행 중이던 재생은 즉시 끊긴다.
 */
class SpeechPlayer {
  private audio: HTMLAudioElement | null = null;
  private token = 0;
  private cancel: (() => void) | null = null;
  private cooldownTimer: number | null = null;
  private ttsCache = new Map<string, string>();
  private snap: PlayerSnapshot = { speaking: false, busy: false, blocked: false };
  private listeners = new Set<() => void>();

  private el(): HTMLAudioElement {
    if (!this.audio) {
      this.audio = new Audio();
      this.audio.preload = "auto";
    }
    return this.audio;
  }

  subscribe = (cb: () => void) => {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  };

  getSnapshot = () => this.snap;

  private set(patch: Partial<PlayerSnapshot>) {
    const next = { ...this.snap, ...patch };
    if (next.speaking === this.snap.speaking && next.busy === this.snap.busy && next.blocked === this.snap.blocked) return;
    this.snap = next;
    this.listeners.forEach((l) => l());
  }

  /** 사용자 클릭 안에서 동기로 한 번 호출해 이후 자동 재생이 막히지 않게 한다. */
  unlock(): void {
    try {
      const a = this.el();
      a.src = URL.createObjectURL(encodeWav(new Float32Array(160)));
      const p = a.play();
      if (p) p.then(() => this.set({ blocked: false })).catch(() => undefined);
    } catch {
      /* 무시: 재생은 이후 speak() 에서 다시 시도한다 */
    }
  }

  stop(): void {
    this.token++;
    this.halt();
    this.finish();
  }

  async speak(speech: Speech | null): Promise<void> {
    const my = ++this.token;
    this.halt();
    if (!speech || !speech.text.trim()) {
      this.finish();
      return;
    }
    this.begin();
    try {
      let outcome: "ok" | "fail" | "blocked" = "fail";
      if (speech.audio_url) outcome = await this.playUrl(speech.audio_url);
      if (my !== this.token || outcome === "blocked") return;
      if (outcome === "fail") {
        const url = await this.ttsUrl(speech.text);
        if (my !== this.token) return;
        if (url) outcome = await this.playUrl(url);
      }
      if (my !== this.token || outcome === "blocked") return;
      if (outcome === "fail" && MOCK) await this.browserSpeak(speech.text, my);
    } finally {
      if (my === this.token) this.finish();
    }
  }

  private begin() {
    if (this.cooldownTimer !== null) {
      window.clearTimeout(this.cooldownTimer);
      this.cooldownTimer = null;
    }
    this.set({ speaking: true, busy: true });
  }

  private finish() {
    this.set({ speaking: false });
    if (this.cooldownTimer !== null) window.clearTimeout(this.cooldownTimer);
    this.cooldownTimer = window.setTimeout(() => {
      this.cooldownTimer = null;
      this.set({ busy: false });
    }, VAD_COOLDOWN_MS);
  }

  private halt() {
    this.cancel?.();
    this.cancel = null;
    try {
      this.audio?.pause();
    } catch {
      /* 무시 */
    }
    if (MOCK && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  private playUrl(url: string): Promise<"ok" | "fail" | "blocked"> {
    return new Promise((resolve) => {
      const a = this.el();
      const done = (r: "ok" | "fail" | "blocked") => {
        a.removeEventListener("ended", onEnd);
        a.removeEventListener("error", onErr);
        if (this.cancel === cancel) this.cancel = null;
        resolve(r);
      };
      const onEnd = () => done("ok");
      const onErr = () => done("fail");
      const cancel = () => done("fail");
      a.addEventListener("ended", onEnd);
      a.addEventListener("error", onErr);
      this.cancel = cancel;
      a.src = url;
      const p = a.play();
      if (p) {
        p.then(() => this.set({ blocked: false })).catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "NotAllowedError") {
            this.set({ blocked: true });
            done("blocked");
          } else {
            done("fail");
          }
        });
      }
    });
  }

  private async ttsUrl(text: string): Promise<string | null> {
    const hit = this.ttsCache.get(text);
    if (hit) return hit;
    try {
      const blob = await api.tts(text);
      if (blob.size === 0) return null;
      const url = URL.createObjectURL(blob);
      this.ttsCache.set(text, url);
      if (this.ttsCache.size > TTS_CACHE_MAX) {
        const oldest = this.ttsCache.keys().next().value;
        if (oldest !== undefined) {
          URL.revokeObjectURL(this.ttsCache.get(oldest) as string);
          this.ttsCache.delete(oldest);
        }
      }
      return url;
    } catch {
      return null;
    }
  }

  /** 목업 모드 전용: 서버 TTS 가 없으니 브라우저 음성합성으로 대신 읽는다. */
  private browserSpeak(text: string, my: number): Promise<void> {
    return new Promise((resolve) => {
      if (!("speechSynthesis" in window)) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ko-KR";
      // 일부 환경(헤드리스 등)에서는 end 이벤트가 오지 않아 마이크가 영영 멈춘다. 길이 기반으로 상한을 둔다.
      const timer = window.setTimeout(() => resolve(), Math.max(3000, text.length * 450));
      const done = () => {
        window.clearTimeout(timer);
        resolve();
      };
      u.onend = done;
      u.onerror = done;
      this.cancel = done;
      if (my !== this.token) return resolve();
      window.speechSynthesis.speak(u);
    });
  }
}

export const player = new SpeechPlayer();

export function usePlayer(): PlayerSnapshot {
  return useSyncExternalStore(player.subscribe, player.getSnapshot);
}
