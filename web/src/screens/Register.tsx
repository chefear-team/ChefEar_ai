import { useState, type FormEvent } from "react";
import { Chips, Hero } from "../components/common";
import { VoiceProgress } from "../components/VoiceProgress";
import { type ScreenProps } from "./Cooking";

function Dots({ total, current }: { total: number; current: number }) {
  return (
    <div className="regdots" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={i + 1 <= current ? "on" : ""} />
      ))}
    </div>
  );
}

function CancelButton({ act }: ScreenProps) {
  return (
    <button type="button" className="btn lg" onClick={() => act({ type: "cancel" })}>
      취소
    </button>
  );
}

export function RegisterDishNameScreen(props: ScreenProps) {
  const { state, act } = props;
  const guess = state.registration?.guess ?? null;
  const [name, setName] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = name.trim();
    if (!v) return;
    act({ type: "register_dish_name", value: v });
    setName("");
  };
  return (
    <>
      <p className="hint">새 레시피 등록 · 1 / 3 · 요리명</p>
      <Dots total={3} current={1} />
      <h2 className="q">어떤 요리인가요?</h2>
      {guess && (
        <div className="callout">
          <p>
            짐작한 이름: &quot;<strong>{guess}</strong>&quot; — 맞으면 &quot;네&quot;, 다르면 이름을 말씀해주세요
          </p>
          <button type="button" className="btn lg primary" onClick={() => act({ type: "register_dish_name", value: guess })}>
            네, 맞아요
          </button>
        </div>
      )}
      <form className="stack" onSubmit={submit}>
        <label htmlFor="dish-name">요리 이름</label>
        <input id="dish-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 문어초무침" autoComplete="off" />
        <button type="submit" className="btn lg primary" disabled={!name.trim()}>
          다음
        </button>
      </form>
      <div className="stack">
        <CancelButton {...props} />
      </div>
    </>
  );
}

export function RegisterIngredientsScreen(props: ScreenProps) {
  const { state, act } = props;
  const reg = state.registration;
  const [text, setText] = useState("");
  const add = (e: FormEvent) => {
    e.preventDefault();
    const items = text.split(",").map((x) => x.trim()).filter(Boolean);
    if (items.length === 0) return;
    act({ type: "register_add_ingredients", items });
    setText("");
  };
  return (
    <>
      <p className="hint">{reg?.dish_name ?? "새 레시피"} · 2 / 3 · 재료</p>
      <Dots total={3} current={2} />
      <h2 className="q">재료를 알려주세요</h2>
      <Chips items={reg?.ingredients ?? []} />
      <form className="stack" onSubmit={add}>
        <label htmlFor="ing-new">재료 추가(쉼표로 여러 개 가능)</label>
        <div className="row">
          <input id="ing-new" maxLength={400} value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 두부, 감자" autoComplete="off" />
          <button type="submit" className="btn" disabled={!text.trim()}>
            추가
          </button>
        </div>
      </form>
      <div className="stack">
        {(reg?.ingredients.length ?? 0) > 0 && (
          <button type="button" className="btn xl primary" onClick={() => act({ type: "register_ingredients_done" })}>
            네, 맞아요
          </button>
        )}
        <CancelButton {...props} />
      </div>
    </>
  );
}

function StepRow({ index, text, act }: { index: number; text: string; act: ScreenProps["act"] }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  if (editing) {
    return (
      <li className="steprow editing">
        <input maxLength={200} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label={`${index + 1}번째 단계 수정`} />
        <div className="row">
          <button
            type="button"
            className="btn primary"
            disabled={!draft.trim()}
            onClick={() => {
              act({ type: "register_edit_step", index, text: draft.trim() });
              setEditing(false);
            }}
          >
            저장
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setDraft(text);
              setEditing(false);
            }}
          >
            취소
          </button>
        </div>
      </li>
    );
  }
  return (
    <li className="steprow">
      <span className="step-no">{index + 1}</span>
      <p>{text}</p>
      <div className="row tight">
        <button
          type="button"
          className="btn small"
          onClick={() => {
            setDraft(text);
            setEditing(true);
          }}
        >
          수정
        </button>
        <button type="button" className="btn small danger" onClick={() => act({ type: "register_delete_step", index })}>
          삭제
        </button>
      </div>
    </li>
  );
}

export function RegisterStepsScreen(props: ScreenProps) {
  const { state, act } = props;
  const reg = state.registration;
  const [text, setText] = useState("");
  const add = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    act({ type: "register_add_step", text: t });
    setText("");
  };
  const steps = reg?.instructions ?? [];
  return (
    <>
      <p className="hint">{reg?.dish_name ?? "새 레시피"} · 3 / 3 · 조리 순서</p>
      <Dots total={3} current={3} />
      <h2 className="q">조리 순서를 알려주세요</h2>
      <ol className="steplist">
        {steps.map((s, i) => (
          // 서버가 순서를 정하므로 index+내용을 키로 쓴다(수정 중 상태가 다른 행으로 옮겨가지 않게)
          <StepRow key={`${i}-${s}`} index={i} text={s} act={act} />
        ))}
      </ol>
      <form className="stack" onSubmit={add}>
        <label htmlFor="step-new">순서 추가</label>
        <div className="row">
          <input id="step-new" maxLength={200} value={text} onChange={(e) => setText(e.target.value)} placeholder="새 단계 추가" autoComplete="off" />
          <button type="submit" className="btn" disabled={!text.trim()}>
            단계 추가
          </button>
        </div>
      </form>
      <div className="stack">
        {steps.length > 0 && (
          <button type="button" className="btn xl primary" onClick={() => act({ type: "register_save" })}>
            네, 저장할게요
          </button>
        )}
        <CancelButton {...props} />
      </div>
    </>
  );
}

export function CompleteScreen({ state, act, onMyRecipes }: ScreenProps) {
  const dish = state.registration?.dish_name ?? state.recipe?.dish_name ?? "레시피";
  return (
    <>
      <Hero icon="check" tone="positive" title="저장이 완료됐어요!">
        <p>{dish}, 등록한 계정으로 바로 조회할 수 있어요.</p>
      </Hero>
      {state.recipe?.recipe_id && <VoiceProgress recipeId={state.recipe.recipe_id} />}
      <div className="stack">
        {onMyRecipes && (
          <button type="button" className="btn xl primary" onClick={onMyRecipes}>
            내 레시피 보기
          </button>
        )}
        <button type="button" className={onMyRecipes ? "btn lg" : "btn xl primary"} onClick={() => act({ type: "home" })}>
          처음 화면으로
        </button>
      </div>
    </>
  );
}
