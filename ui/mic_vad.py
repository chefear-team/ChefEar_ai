"""상시 마이크용 실시간 VAD(음성구간감지) 세그먼터 - 2026-08-20 추가.

streamlit-webrtc가 브라우저 마이크에서 실시간으로 오디오 프레임을 넘겨주는데,
그건 그냥 끊김 없이 이어지는 오디오 스트림일 뿐이다("다음"이라는 한 마디가
어디서 시작해서 어디서 끝나는지는 모른다). 이 파일의 MicVadSegmenter가 그
프레임들을 하나씩 받아서, silero-vad로 "지금 말하고 있다/조용하다"를 판단하고,
"말하다가 min_silence_duration_ms만큼 조용해지면 거기까지가 한 발화"라고
잘라서 오디오 배열 하나로 돌려준다. 그 결과를 stt.infer.stt_transcribe()에
넣으면 텍스트가 되고, 그 텍스트를 orchestration.pipeline.handle_utterance()에
넣으면 텍스트 테스트 화면과 똑같은 파이프라인을 탄다.
"""
from __future__ import annotations

from collections import deque

import numpy as np


class MicVadSegmenter:
    """오디오 프레임을 계속 넣어주면(feed), 발화 하나가 끝날 때마다 그 구간의
    16kHz 모노 float32 오디오 배열을 돌려준다. 아직 발화 중이거나 무음이면 None.
    """

    CHUNK_SAMPLES = 512  # silero-vad가 16kHz에서 요구하는 고정 청크 크기(32ms)

    # 2026-08-23 추가 — "된장찌개"가 "상장찌개"로 인식되는 등 첫 음절이 잘려나가는 문제
    # 실측 확인. silero-vad의 VADIterator는 "말 시작"이라고 확정하기까지 몇 청크의 증거가
    # 쌓여야 event를 내보내는데(감지 지연), 예전 코드는 그 event가 뜬 청크부터만 담아서
    # 실제 발화 시작 부분(첫 자음/모음)이 통째로 잘려나갔다. 청크 10개(32ms*10≈320ms)를
    # 항상 미리 들고 있다가, "말 시작" event가 뜨는 순간 그 사전 버퍼를 앞에 붙여서
    # 실제 발화 시작 지점을 보존한다.
    PRE_ROLL_CHUNKS = 10

    def __init__(self, min_silence_duration_ms: int = 600, threshold: float = 0.5):
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

        # 2026-08-23 추가 — "테스트용 wav 파일로는 STT가 멀쩡한데 실시간 마이크만 넣으면
        # (매번 다른 음절이) 이상하게 들린다"는 리포트로 실측 확인한 원인 수정.
        #
        # webrtc 오디오 프레임은 보통 20ms 단위(48kHz 기준 960샘플)로 하나씩 들어오는데,
        # 예전 코드는 그 프레임 하나가 들어올 때마다 매번 독립적으로
        # librosa.resample(frame, 48000, 16000)을 불렀다. librosa.resample()은 "짧은
        # 조각 하나를 통째로" 처리하는 함수라 앞뒤 프레임의 문맥을 전혀 모른 채 매번 새
        # 필터를 거는 것과 같다 — 발화 4초짜리면 프레임-프레임 이음매가 200개 가까이
        # 생기고, 그 이음매마다 미세한 위상 불연속(작은 클릭/링잉)이 낀다. 파일 하나를
        # 통째로 리샘플링하는 배치 테스트 경로는 이 이음매가 시작·끝 두 군데뿐이라
        # 이 문제가 안 보였던 것.
        #
        # 하필 이 이음매 잡음이 된소리(ㅉ)/거센소리(ㅊ)처럼 몇 ms짜리 미세한 타이밍
        # 차이로 구분되는 음소를 잘 뭉갠다("찌개"→"치게" 등) — 그리고 프레임 경계가
        # 정확히 어느 음소 위에 걸리는지는 네트워크 타이밍에 달려있어 매번 달라지므로,
        # 매번 다른 음절이 깨지는 것도 이걸로 설명된다.
        #
        # 고친 방식: VAD 판정(말하는지/조용한지)에는 그대로 프레임 단위 리샘플링을 쓴다
        # (에너지 패턴만 보면 되니 이 정도 잡음엔 안 민감함). 대신 실제로 Whisper에
        # 넘길 오디오는 원본 샘플레이트(예: 48kHz) 그대로 별도 버퍼에 쌓아뒀다가,
        # VAD가 "발화 끝"을 확정하는 시점에 그 구간 전체를 딱 한 번만 리샘플링한다
        # (_pending_raw/_speech_chunks_raw/_pre_roll_raw가 그 원본 샘플레이트 버퍼).
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

            if event is not None and "end" in event:
                self._in_speech = False
                if self._speech_chunks_raw:
                    # 여기서 딱 한 번만 리샘플링한다 — 발화 전체를 이어붙인 원본
                    # 샘플레이트 오디오를 한 덩어리로 처리하므로 프레임 단위 리샘플링
                    # 때 생기던 이음매 잡음이 없다.
                    full_raw = np.concatenate(self._speech_chunks_raw)
                    result = self._resample(full_raw, self._raw_sample_rate, 16000)
                    # 2026-08-23 임시 진단 — "녹음된 게 내 목소리가 아니다" 리포트 원인 파악용.
                    # 리샘플링 등 이 파일의 가공을 거치기 전 원본(raw, 원본 샘플레이트)도
                    # 호출부(voice_io.py)가 같이 덤프할 수 있게 남겨둔다. 원인 확인되면 지울 것.
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

        2026-08-23 수정 — "녹음이 내 목소리가 아니다"(음이 낮고 늘어져 들림) 리포트 원인
        실측 확인: 예전 코드는 "배열의 더 작은 축이 채널 축"이라고 짐작했는데, 실제로는
        av.AudioFrame.to_ndarray()가 stereo/packed(s16, non-planar) 프레임을
        (채널, 샘플) 모양이 아니라 **(1, 샘플수*채널수)짜리 한 줄**로 준다(실측:
        frame.samples=960인데 shape=(1, 1920)). 그 모양에선 "더 작은 축=채널"이라는
        가정이 깨져서 L0,R0,L1,R1...이 채널 분리 없이 그냥 순서대로 이어진 모노 샘플인
        것처럼 처리됐다 — 그러면 실제 시간의 2배 길이 가짜 파형이 만들어지고, 그걸
        16kHz라고 우기며 재생하니 훨씬 느리고 음높이 낮은(뭉개진, 다른 사람 목소리 같은)
        소리가 나왔던 것. 배열 모양만으로는 인터리브 여부를 알 수 없어서, 호출부가
        frame.layout에서 알아낸 실제 채널 수(channels)를 받아 명시적으로 나눈다.
        """
        samples = np.asarray(samples)
        if np.issubdtype(samples.dtype, np.integer):
            # int16 PCM(webrtc/av 기본 포맷) -> [-1, 1] float32
            samples = samples.astype(np.float32) / 32768.0
        else:
            samples = samples.astype(np.float32)

        if channels <= 1:
            return samples.reshape(-1)

        # 2026-08-23 임시 진단 — "여전히 굵고 안 들리는 목소리로 녹음됨"(위 인터리브
        # 수정 이후에도 재현, max_amp=0.9151/rms=0.0755로 크레스트 팩터 비정상 확인)
        # 원인을 좁히기 위해, (L+R)/2 평균 대신 L채널만 뽑아 비교한다 — 이 마이크가
        # 진짜 2채널을 서로 다르게(에코 캔슬 처리 등) 담고 있다면 평균이 위상 간섭
        # (콤필터링)을 일으켜 먹먹/저음으로 들릴 수 있다는 가설 테스트. 이 가설이
        # 맞으면 L채널만 써도 이 문제가 사라져야 한다 — 아니라면 원인은 다른 곳
        # (AGC 클리핑 등)이라는 뜻이니 아래 두 return을 각각 .mean(axis=0)/
        # .mean(axis=1)로 되돌릴 것.
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
