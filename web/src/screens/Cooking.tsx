import type { Action, State } from "../types";
import { Badge, Chat, Chips, Hero, Icon, PlayIcon } from "../components/common";
import { usePlayer } from "../lib/player";

export interface ScreenProps {
  state: State;
  act: (a: Action) => void;
  onReplay?: () => void;
  /** 마이레시피 목록을 연다. 로그인했을 때만 넘어온다. */
  onMyRecipes?: () => void;
}

function NavButtons({ act }: { act: ScreenProps["act"] }) {
  return (
    <div className="navrow">
      <button type="button" className="btn" onClick={() => act({ type: "nav", name: "이전" })}>
        이전
      </button>
      <button type="button" className="btn" onClick={() => act({ type: "nav", name: "다시" })}>
        다시
      </button>
      <button type="button" className="btn primary" onClick={() => act({ type: "nav", name: "다음" })}>
        다음
      </button>
    </div>
  );
}

/** 원본 목업(03_cooking_step.html)의 파형 모양. 실제 음성 파형이 아니라 모양만 같다. 읽어 주는 동안 출렁인다. */
const WAVE_HEIGHTS = [6, 10, 16, 24, 14, 22, 28, 18, 26, 12, 20, 9, 16, 24, 14, 8, 12, 6, 10, 6, 14, 22, 12, 18, 8, 16, 24, 10, 6, 12];

function Player({ onReplay }: { onReplay?: () => void }) {
  const { speaking } = usePlayer();
  return (
    <div className="player">
      <button type="button" className="play-btn" aria-label="다시 듣기" onClick={onReplay} disabled={!onReplay}>
        <PlayIcon />
      </button>
      <span className={`wave ${speaking ? "playing" : ""}`} aria-hidden="true">
        {WAVE_HEIGHTS.map((h, i) => (
          <span key={i} style={{ height: h, ["--i" as string]: i }} />
        ))}
      </span>
    </div>
  );
}

export function StartScreen({ state, act, onMyRecipes }: ScreenProps) {
  return (
    <>
      <Hero icon="mic" title="무엇을 만들고 싶으세요?">
        <p>숫자 메뉴 없이, 하고 싶은 말을 편하게 그대로 말씀해주세요.</p>
        <p className="faint">예: &quot;된장찌개 어떻게 만들어?&quot;</p>
      </Hero>
      <Chat messages={state.chat} />
      <div className="stack">
        <button type="button" className="btn lg" onClick={() => act({ type: "register_start" })}>
          새 레시피 등록하기{state.logged_in ? "" : " (로그인 필요)"}
        </button>
        {onMyRecipes && (
          <button type="button" className="btn lg" onClick={onMyRecipes}>
            내 레시피 보기
          </button>
        )}
      </div>
    </>
  );
}

export function RecipeConfirmScreen({ state, act }: ScreenProps) {
  const r = state.recipe;
  return (
    <>
      <Badge tone="good">조회수 1위 표준 레시피</Badge>
      <Hero title={r?.dish_name ?? "레시피"}>
        <p>이걸로 시작할까요?</p>
      </Hero>
      <Chat messages={state.chat} />
      <Chips items={r?.ingredients ?? []} label="재료 미리보기" />
      <div className="stack">
        <button type="button" className="btn xl primary" onClick={() => act({ type: "start_cooking" })}>
          응, 시작할게요
        </button>
        <button type="button" className="btn lg" onClick={() => act({ type: "other_recipe" })}>
          다른 레시피 찾을래요
        </button>
      </div>
    </>
  );
}

export function CookingStepScreen({ state, act, onReplay }: ScreenProps) {
  const r = state.recipe;
  if (!r || r.steps.length === 0) {
    return (
      <Hero icon="question" tone="warn" title="레시피 정보를 불러오지 못했어요">
        <button type="button" className="btn lg" onClick={() => act({ type: "home" })}>
          처음 화면으로
        </button>
      </Hero>
    );
  }
  const total = r.total || r.steps.length;
  const n = Math.min(Math.max(r.step_number, 1), total);
  const current = r.steps.find((s) => s.step_number === n) ?? r.steps[n - 1];
  return (
    <>
      <div className="step-head">
        <Badge>
          {r.dish_name} · {n} / {total} 단계
        </Badge>
      </div>

      <article className="stepcard" aria-live="polite">
        <nav className="stepdots" aria-label="단계 바로가기">
          {r.steps.map((s) => (
            <button
              key={s.step_number}
              type="button"
              className={`dotbtn ${s.step_number === n ? "current" : s.step_number < n ? "done" : ""}`}
              aria-current={s.step_number === n ? "step" : undefined}
              aria-label={`${s.step_number}단계로 이동`}
              onClick={() => act({ type: "goto_step", step_number: s.step_number })}
            />
          ))}
        </nav>

        <div className="step-line">
          <button
            type="button"
            className="arrow"
            aria-label="이전 단계"
            disabled={n <= 1}
            onClick={() => act({ type: "nav", name: "이전" })}
          >
            <Icon name="chevronLeft" size={14} />
          </button>
          <p className="step-title">
            {n}. {current?.text}
          </p>
          <button
            type="button"
            className="arrow"
            aria-label="다음 단계"
            onClick={() => act({ type: "nav", name: "다음" })}
          >
            <Icon name="chevronRight" size={14} />
          </button>
        </div>

        <Player onReplay={onReplay} />
      </article>

      <Chips items={r.ingredients} label="오늘의 재료" />
      <Chat messages={state.chat} />
      <NavButtons act={act} />
    </>
  );
}

export function CookingCompleteScreen({ state, act }: ScreenProps) {
  const dish = state.recipe?.dish_name ?? "레시피";
  return (
    <>
      <Hero icon="check" tone="positive" title="요리가 완성됐어요!">
        <p>{dish}, 수고하셨어요.</p>
      </Hero>
      <div className="stack">
        <button type="button" className="btn xl primary" onClick={() => act({ type: "home" })}>
          처음 화면으로
        </button>
      </div>
    </>
  );
}

export function UnclassifiedScreen({ state, act }: ScreenProps) {
  const cooking = state.recipe !== null;
  return (
    <>
      <Hero icon="question" tone="warn" title="잘 이해하지 못했어요">
        <p>죄송해요, 다시 한번 말씀해주시겠어요? 안 될 때는 아래 버튼으로도 진행할 수 있어요.</p>
      </Hero>
      <Chat messages={state.chat} />
      {cooking && <NavButtons act={act} />}
      <div className="stack">
        <button type="button" className="btn lg" onClick={() => act({ type: "home" })}>
          처음 화면으로
        </button>
      </div>
    </>
  );
}
