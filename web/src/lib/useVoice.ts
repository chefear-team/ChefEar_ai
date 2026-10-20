import { useCallback, useEffect, useRef, useState } from "react";
import type { MicVAD } from "@ricky0123/vad-web";
import { encodeWav } from "./wav";

export type VoicePhase = "off" | "loading" | "on" | "error";

interface Options {
  /** true 일 때만 듣는다(음성 쓰는 화면 && 재생 중 아님 && 요청 처리 중 아님). */
  gate: boolean;
  /** 발화가 끝날 때마다 16kHz 모노 16-bit WAV 로 넘겨준다. */
  onUtterance: (wav: Blob) => void;
}

const ASSET_BASE = `${import.meta.env.BASE_URL}vad/`;

/**
 * 상시 마이크. @ricky0123/vad-web(silero VAD)을 브라우저에서 돌려 발화 구간만 잘라 낸다.
 *  - enable(): 사용자 클릭 안에서 호출. VAD 코드는 이때 동적 import 한다.
 *  - gate 가 false 가 되면 vad.pause() 로 프레임 처리를 멈추고(재생 소리가 마이크로 들어가지 않게),
 *    true 가 되면 vad.start() 로 다시 듣는다. gate 에는 "재생 끝난 뒤 600ms" 가 이미 반영돼 있다.
 */
export function useVoice({ gate, onUtterance }: Options) {
  const [phase, setPhase] = useState<VoicePhase>("off");
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [hearing, setHearing] = useState(false);

  const vadRef = useRef<MicVAD | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const loadingRef = useRef(false);
  const chainRef = useRef<Promise<void>>(Promise.resolve());

  const want = phase === "on" && !muted && gate;
  const wantRef = useRef(want);
  wantRef.current = want;
  const onUtteranceRef = useRef(onUtterance);
  onUtteranceRef.current = onUtterance;

  /** 사용자 클릭 핸들러 안에서 동기로 호출해야 AudioContext 가 자동 재생 정책에 걸리지 않는다. */
  const prepare = useCallback(() => {
    if (ctxRef.current || typeof AudioContext === "undefined") return;
    try {
      ctxRef.current = new AudioContext();
      void ctxRef.current.resume();
    } catch {
      ctxRef.current = null;
    }
  }, []);

  /** 브라우저 마이크 연결(소리 입력 트랙)을 실제로 닫는다. 주소창의 마이크 표시등도 꺼진다. */
  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const fail = useCallback((e: unknown) => {
    stopStream();
    vadRef.current = null; // 다시 켜기(enable)로 재시도할 수 있게 비운다
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") {
      setError("마이크 권한이 없어요. 브라우저 설정에서 허용하거나, 아래 입력창과 버튼으로 계속할 수 있어요.");
    } else if (name === "NotFoundError") {
      setError("마이크를 찾지 못했어요. 아래 입력창과 버튼으로 계속할 수 있어요.");
    } else {
      setError("음성 인식 기능을 불러오지 못했어요. 아래 입력창과 버튼으로 계속할 수 있어요.");
    }
    setPhase("error");
    setHearing(false);
  }, [stopStream]);

  const enable = useCallback(async () => {
    if (loadingRef.current || vadRef.current) return;
    loadingRef.current = true;
    setPhase("loading");
    setError(null);
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new DOMException("no mediaDevices", "NotFoundError");
      }
      const { MicVAD } = await import("@ricky0123/vad-web");
      const vad = await MicVAD.new({
        model: "v5",
        startOnLoad: false,
        baseAssetPath: ASSET_BASE,
        onnxWASMBasePath: ASSET_BASE,
        audioContext: ctxRef.current ?? undefined,
        // 일시 정지(재생 중·처리 중·폼 화면)에서는 마이크 연결을 켠 채로 두고 듣기만 전환한다(재연결 지연 방지).
        // 연결을 실제로 닫는 건 release() 뿐이다 — 마이크 끄기와 로그아웃에서 부른다.
        getStream: async () => {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, autoGainControl: true, noiseSuppression: true },
          });
          streamRef.current = stream;
          return stream;
        },
        pauseStream: async () => undefined,
        resumeStream: async (stream) => stream,
        ortConfig: (ort) => {
          ort.env.wasm.numThreads = 1; // SharedArrayBuffer(교차 출처 격리) 없이도 동작
          ort.env.logLevel = "error";
        },
        redemptionMs: 1000,
        onSpeechStart: () => {
          if (wantRef.current) setHearing(true);
        },
        onVADMisfire: () => setHearing(false),
        onSpeechEnd: (audio: Float32Array) => {
          setHearing(false);
          if (!wantRef.current) return; // 재생 중/쿨다운/처리 중에 잡힌 소리는 버린다
          onUtteranceRef.current(encodeWav(audio, 16000));
        },
      });
      vadRef.current = vad;
      setPhase("on");
    } catch (e) {
      fail(e);
    } finally {
      loadingRef.current = false;
    }
  }, [fail]);

  /** 마이크 연결을 닫는다(듣기 중지 + 브라우저 마이크 표시등 꺼짐). 다시 쓰려면 enable() 을 부른다. */
  const release = useCallback(async () => {
    const vad = vadRef.current;
    vadRef.current = null;
    setPhase("off");
    setHearing(false);
    setError(null);
    stopStream();
    if (vad) {
      try {
        await vad.destroy();
      } catch {
        /* 이미 닫혔으면 무시 */
      }
    }
  }, [stopStream]);

  /** 로그아웃용: 연결을 닫고 음소거 표시도 되돌려 다음 로그인 때 처음 상태로 시작하게 한다. */
  const disable = useCallback(async () => {
    setMuted(false);
    await release();
  }, [release]);

  // want 가 바뀔 때마다 VAD 를 시작/멈춤. 직렬화해서 start/pause 가 엇갈리지 않게 한다.
  useEffect(() => {
    if (phase !== "on") return;
    chainRef.current = chainRef.current.then(async () => {
      const vad = vadRef.current;
      if (!vad) return;
      try {
        if (wantRef.current && !vad.listening) {
          if (ctxRef.current?.state === "suspended") await ctxRef.current.resume();
          await vad.start();
        } else if (!wantRef.current && vad.listening) {
          await vad.pause();
          setHearing(false);
        }
      } catch (e) {
        fail(e);
      }
    });
  }, [want, phase, fail]);

  useEffect(
    () => () => {
      const vad = vadRef.current;
      vadRef.current = null;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      if (vad) void vad.destroy().catch(() => undefined);
      void ctxRef.current?.close().catch(() => undefined);
      ctxRef.current = null;
    },
    [],
  );

  /** 끄면 마이크 연결을 실제로 닫고, 켜면 다시 연결한다. */
  const toggleMuted = useCallback(() => {
    if (!muted) {
      setMuted(true);
      void release();
    } else {
      setMuted(false);
      void enable();
    }
  }, [muted, release, enable]);

  return { phase, error, muted, hearing, listening: want, prepare, enable, release, disable, toggleMuted };
}
