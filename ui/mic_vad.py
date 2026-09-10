"""상시 마이크용 실시간 VAD(음성구간감지) 세그먼터 — silero-vad로 발화 구간을 잘라 STT에 넘긴다."""
from __future__ import annotations

import os
from collections import deque

import numpy as np

_ENV_VAD_THRESHOLD = os.environ.get("VAD_THRESHOLD")
_ENV_VAD_MIN_SILENCE_MS = os.environ.get("VAD_MIN_SILENCE_MS")


class MicVadSegmenter:
    """오디오 프레임을 계속 넣어주면(feed), 발화 하나가 끝날 때마다 그 구간의
    16kHz 모노 float32 오디오 배열을 돌려준다. 아직 발화 중이거나 무음이면 None.
    """

    CHUNK_SAMPLES = 512  # silero-vad가 16kHz에서 요구하는 고정 청크 크기(32ms)

    PRE_ROLL_CHUNKS = 10

    def __init__(
        self,
        min_silence_duration_ms: int = int(_ENV_VAD_MIN_SILENCE_MS) if _ENV_VAD_MIN_SILENCE_MS else 750,
        threshold: float = float(_ENV_VAD_THRESHOLD) if _ENV_VAD_THRESHOLD else 0.5,
        max_speech_duration_s: float = 10.0,
    ):
        from silero_vad import VADIterator, load_silero_vad

        self._iterator = VADIterator(
            load_silero_vad(),
            threshold=threshold,
            sampling_rate=16000,
            # 사람이 문장 사이에 숨 쉬는 정도의 짧은 멈춤(수백ms)까지 "발화 끝"으로
            # 잘라버리면 "다음"처럼 짧은 단어는 괜찮아도 긴 문장이 중간에 끊길 수
            # 있다. 600ms면 자연스러운 문장 내 쉼은 넘기고, 진짜 "말 다 끝남"만
            # 잡아내는 편(값 자체는 실측 튜닝 전 임시값, intent_classifier.THRESHOLD와
            # 같은 성격).
            min_silence_duration_ms=min_silence_duration_ms,
        )

        if os.environ.get("VAD_DEBUG"):
            _real_model = self._iterator.model

            def _debug_model(*args, **kwargs):
                prob_tensor = _real_model(*args, **kwargs)
                try:
                    print(f"[VAD_DEBUG] prob={prob_tensor.item():.3f} threshold={threshold}", flush=True)
                except Exception:  # noqa: BLE001 — 진단 로그 실패가 실제 VAD 판정에 영향 주면 안 됨
                    pass
                return prob_tensor

            self._iterator.model = _debug_model

        self._max_speech_duration_s = max_speech_duration_s

        self._pending16k = np.zeros(0, dtype=np.float32)  # VAD 판정 전용(리샘플됨)
        self._pending_raw = np.zeros(0, dtype=np.float32)  # 최종 STT 입력용(원본 샘플레이트)
        self._raw_sample_rate: int | None = None  # feed()에 들어오는 원본 sr(세션 내내 고정 가정)

        self._speech_chunks_raw: list[np.ndarray] = []
        self._pre_roll_raw: deque[np.ndarray] = deque(maxlen=self.PRE_ROLL_CHUNKS)
        self._in_speech = False

        # 임시 진단용(위 feed()의 "end" 분기 주석 참고) — 가공 전 원본 오디오/샘플레이트.
        self.last_raw_utterance: np.ndarray | None = None
        self.last_raw_sample_rate: int | None = None

    def reset(self) -> None:
        self._iterator.reset_states()
        self._pending16k = np.zeros(0, dtype=np.float32)
        self._pending_raw = np.zeros(0, dtype=np.float32)
        self._speech_chunks_raw = []
        self._pre_roll_raw.clear()
        self._in_speech = False

    def feed(self, samples: np.ndarray, sample_rate: int, channels: int = 1) -> np.ndarray | None:
        """samples: 임의의 sample_rate/모양(모노 또는 다채널, int16 또는 float)의
        오디오 조각 하나. channels는 그 프레임의 실제 채널 수(호출부가 av.AudioFrame.layout
        등에서 알아내서 넘겨줘야 함 — 배열 모양만으로는 인터리브 여부를 못 알아낸다, 아래
        _to_mono_float32() 주석 참고). 이번 호출로 발화 하나가 완성됐으면 그 오디오(16kHz
        모노 float32)를 반환하고, 아니면 None을 반환한다.
        """
        mono_raw = self._to_mono_float32(samples, channels)
        self._raw_sample_rate = sample_rate
        mono16k = self._resample(mono_raw, sample_rate, 16000)

        self._pending16k = np.concatenate([self._pending16k, mono16k])
        self._pending_raw = np.concatenate([self._pending_raw, mono_raw])

        # 16kHz 청크(VAD 판정용) 하나(32ms)에 대응하는 원본 샘플레이트 구간의 길이.
        # 프레임마다 리샘플링 출력 길이가 1샘플 정도씩 흔들릴 수 있어 두 버퍼가 완벽히
        # 같은 속도로 안 줄어들 수 있는데, 아래 while 조건이 둘 다 채워질 때까지
        # 기다리므로 그 차이는 다음 feed() 호출에서 자연히 흡수된다(발화 전체(수 초) 기준
        # 몇 ms 오차는 STT 입력 앞뒤에 무음이 살짝 더 붙는 정도라 무해함).
        raw_chunk_size = round(self.CHUNK_SAMPLES * sample_rate / 16000)

        result = None
        while len(self._pending16k) >= self.CHUNK_SAMPLES and len(self._pending_raw) >= raw_chunk_size:
            vad_chunk = self._pending16k[: self.CHUNK_SAMPLES]
            self._pending16k = self._pending16k[self.CHUNK_SAMPLES :]
            raw_chunk = self._pending_raw[:raw_chunk_size]
            self._pending_raw = self._pending_raw[raw_chunk_size:]

            event = self._iterator(vad_chunk)

            if event is not None and "start" in event:
                self._in_speech = True
                # pre_roll(발화 시작 직전까지의 원본 샘플레이트 구간)을 앞에 붙여서
                # 감지 지연으로 잘려나갈 뻔한 첫 음절을 복원한다.
                self._speech_chunks_raw = list(self._pre_roll_raw) + [raw_chunk]
            elif self._in_speech:
                # "end" 신호가 이번 청크에서 나오더라도, 이 청크 자체는 아직
                # 발화의 일부(문장 끝자락)이므로 먼저 담아둔다.
                self._speech_chunks_raw.append(raw_chunk)
            else:
                # 아직 발화 시작 전(무음/판단 대기) — 나중에 "start"가 뜨면 쓸 수 있게
                # 최근 청크만 계속 굴려서 들고 있는다.
                self._pre_roll_raw.append(raw_chunk)

            forced_cutoff = False
            if self._in_speech and self._raw_sample_rate:
                elapsed_s = sum(len(c) for c in self._speech_chunks_raw) / self._raw_sample_rate
                if elapsed_s >= self._max_speech_duration_s:
                    forced_cutoff = True
                    self._in_speech = False
                    self._iterator.reset_states()

            if (event is not None and "end" in event) or forced_cutoff:
                self._in_speech = False
                if self._speech_chunks_raw:
                    # 여기서 딱 한 번만 리샘플링한다 — 발화 전체를 이어붙인 원본
                    # 샘플레이트 오디오를 한 덩어리로 처리하므로 프레임 단위 리샘플링
                    # 때 생기던 이음매 잡음이 없다.
                    full_raw = np.concatenate(self._speech_chunks_raw)
                    result = self._resample(full_raw, self._raw_sample_rate, 16000)
                    self.last_raw_utterance = full_raw
                    self.last_raw_sample_rate = self._raw_sample_rate
                self._speech_chunks_raw = []
                self._pre_roll_raw.clear()

        return result

    @staticmethod
    def _to_mono_float32(samples: np.ndarray, channels: int = 1) -> np.ndarray:
        """samples를 모노 float32([-1, 1])로 바꾼다 — 리샘플링은 하지 않는다
        (원본 샘플레이트를 그대로 유지해야 나중에 발화 전체를 한 번에만
        리샘플링할 수 있다).
        """
        samples = np.asarray(samples)
        if np.issubdtype(samples.dtype, np.integer):
            # int16 PCM(webrtc/av 기본 포맷) -> [-1, 1] float32
            samples = samples.astype(np.float32) / 32768.0
        else:
            samples = samples.astype(np.float32)

        if channels <= 1:
            return samples.reshape(-1)

        if samples.ndim == 2 and samples.shape[0] == channels and samples.shape[0] != samples.shape[1]:
            # planar 레이아웃 — 채널마다 행이 분리돼 있음(각 행이 그 채널의 연속된 샘플들).
            return samples[0]

        # packed(인터리브) 레이아웃 — 지금 실측된 경우(shape=(1, 샘플수*채널수)) 포함.
        # [L0, R0, L1, R1, ...] 순서로 붙어있다고 보고 채널별로 나눈 뒤 L채널만 취한다.
        flat = samples.reshape(-1)
        usable = (len(flat) // channels) * channels
        return flat[:usable].reshape(-1, channels)[:, 0]

    @staticmethod
    def _resample(mono: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr:
            return mono
        import librosa

        return librosa.resample(mono, orig_sr=orig_sr, target_sr=target_sr)
