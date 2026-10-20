import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, Hero } from "../components/common";
import { VOICE_ETA } from "../components/VoiceProgress";
import { api } from "../lib/api";
import { errorMessage, errorStatus } from "../lib/errors";
import { LoginOptions } from "./Auth";
import type { MyRecipeSummary } from "../types";

export function LoginRequiredScreen({ onBack }: { onBack: () => void; onDone?: () => void }) {
  return (
    <>
      <Hero icon="lock" title="로그인이 필요해요">
        <p>레시피 등록과 마이레시피는 로그인 후에 쓸 수 있어요. 요리 조회와 안내는 로그인 없이도 돼요.</p>
      </Hero>
      <LoginOptions />
      <div className="stack">
        <button type="button" className="btn lg" onClick={onBack}>
          비로그인으로 둘러보기
        </button>
      </div>
    </>
  );
}

// ---------------- 마이레시피 ----------------

const dateFmt = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("ko-KR");
};

export function MyRecipesScreen({
  loggedIn,
  onEdit,
  onBack,
  onLogin,
  onRegister,
}: {
  loggedIn: boolean;
  onEdit: (id: string) => void;
  onBack: () => void;
  onLogin: () => void;
  onRegister: () => void;
}) {
  const [rows, setRows] = useState<MyRecipeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api.listMyRecipes();
      setRows([...list].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      setError(null);
      setNeedLogin(false);
    } catch (e) {
      if (errorStatus(e) === 401) setNeedLogin(true);
      else setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (!loggedIn) {
      setNeedLogin(true);
      return;
    }
    void load();
  }, [loggedIn, load]);

  // 음성 준비 중인 레시피가 있으면 10초마다 상태를 다시 본다.
  const anyPreparing = rows?.some((r) => !r.audio_ready) ?? false;
  useEffect(() => {
    if (!anyPreparing) return;
    const t = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(t);
  }, [anyPreparing, load]);

  const remove = async (id: string) => {
    try {
      await api.deleteMyRecipe(id);
      setConfirmId(null);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (needLogin) {
    return (
      <>
        <Hero icon="lock" title="로그인이 필요해요">
          <p>마이레시피는 로그인 후에 볼 수 있어요.</p>
        </Hero>
        <div className="stack">
          <button type="button" className="btn xl primary" onClick={onLogin}>
            로그인하기
          </button>
          <button type="button" className="btn lg" onClick={onBack}>
            처음 화면으로
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="row between">
        <h2 className="q">내가 등록한 레시피{rows ? ` · ${rows.length}개` : ""}</h2>
        <button type="button" className="btn small" onClick={() => void load()}>
          새로고침
        </button>
      </div>
      {error && (
        <p className="callout error" role="alert">
          {error}
        </p>
      )}
      {rows === null && !error && <p className="faint">불러오는 중...</p>}
      {rows && rows.length === 0 && (
        <Hero icon="inbox" title="아직 등록한 레시피가 없어요">
          <button type="button" className="btn lg primary" onClick={onRegister}>
            새 레시피 등록하기
          </button>
        </Hero>
      )}
      <ul className="recipelist">
        {rows?.map((r) => (
          <li key={r.recipe_id} className="recipecard">
            <div className="recipe-top">
              <div>
                <div className="recipe-name">{r.dish_name}</div>
                <div className="faint small">{dateFmt(r.created_at)}</div>
              </div>
              {r.audio_ready ? <Badge tone="good">음성 준비 완료</Badge> : <Badge tone="warn">음성 준비 중 · {VOICE_ETA}</Badge>}
            </div>
            {confirmId === r.recipe_id ? (
              <div className="stack">
                <p className="callout error">&quot;{r.dish_name}&quot;를 정말 삭제할까요? 되돌릴 수 없어요.</p>
                <div className="row">
                  <button type="button" className="btn lg danger" onClick={() => void remove(r.recipe_id)}>
                    네, 삭제할게요
                  </button>
                  <button type="button" className="btn lg" onClick={() => setConfirmId(null)}>
                    취소
                  </button>
                </div>
              </div>
            ) : (
              <div className="row">
                <button type="button" className="btn" onClick={() => onEdit(r.recipe_id)}>
                  수정
                </button>
                <button type="button" className="btn danger" onClick={() => setConfirmId(r.recipe_id)}>
                  삭제
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="stack">
        <button type="button" className="btn lg" onClick={onBack}>
          처음 화면으로
        </button>
      </div>
    </>
  );
}

// ---------------- 레시피 수정 ----------------

const STEP_PREFIX = /^\d+\.\s*/;

export function EditRecipeScreen({ id, onClose }: { id: string; onClose: () => void }) {
  const [loaded, setLoaded] = useState(false);
  const [name, setName] = useState("");
  const [ingredients, setIngredients] = useState("");
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getMyRecipe(id)
      .then((r) => {
        if (!alive) return;
        setName(r.dish_name);
        setIngredients(r.ingredients.join(", "));
        setInstructions(r.instructions.map((s) => s.replace(STEP_PREFIX, "")).join("\n"));
        setLoaded(true);
      })
      .catch((e: unknown) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [id]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const dish = name.trim();
    const steps = instructions.split("\n").map((x) => x.trim()).filter(Boolean);
    if (!dish) return setError("요리명을 입력해 주세요.");
    if (steps.length === 0) return setError("조리 순서를 한 단계 이상 적어 주세요.");
    setSaving(true);
    setError(null);
    try {
      await api.updateMyRecipe(id, {
        dish_name: dish,
        ingredients: ingredients.split(",").map((x) => x.trim()).filter(Boolean),
        instructions: steps,
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
    }
  };

  return (
    <form className="stack" onSubmit={save}>
      <h2 className="q">{loaded ? `${name} 수정` : "레시피 수정"}</h2>
      {error && (
        <p className="callout error" role="alert">
          {error}
        </p>
      )}
      {!loaded && !error && <p className="faint">불러오는 중...</p>}
      {loaded && (
        <>
          <label htmlFor="edit-name">요리명</label>
          <input id="edit-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          <label htmlFor="edit-ing">재료 (쉼표로 구분)</label>
          <textarea id="edit-ing" rows={3} maxLength={2400} value={ingredients} onChange={(e) => setIngredients(e.target.value)} />
          <label htmlFor="edit-steps">조리 순서 (한 줄에 한 단계씩)</label>
          <textarea id="edit-steps" rows={9} maxLength={6200} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
          <div className="row">
            <button type="submit" className="btn xl primary" disabled={saving}>
              저장
            </button>
            <button type="button" className="btn xl" onClick={onClose} disabled={saving}>
              취소
            </button>
          </div>
        </>
      )}
      {!loaded && (
        <button type="button" className="btn lg" onClick={onClose}>
          마이레시피로
        </button>
      )}
    </form>
  );
}
