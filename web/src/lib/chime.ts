let ctx: AudioContext | null = null;

/**
 * 말을 알아듣고 처리하는 데 시간이 걸릴 때 한 번 울리는 짧은 알림음(880Hz, 0.16초).
 * 화면을 보지 않고 쓰는 서비스라 "듣고 있다"는 걸 소리로도 알려 준다. 소리를 못 내는 환경이면 조용히 넘어간다.
 */
export function playProcessingChime(): void {
  try {
    if (typeof AudioContext === "undefined") return;
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const t0 = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.16, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + 0.18);
  } catch {
    /* 알림음은 없어도 동작에 지장이 없다 */
  }
}
