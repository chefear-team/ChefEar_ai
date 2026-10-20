// VITE_MOCK=1 일 때 쓰는 브라우저 안의 가짜 API. 서버 없이 화면 흐름을 눌러 볼 수 있다.
// 음성(WAV)은 인식하지 못하고 안내만 돌려준다. 글자 입력과 버튼은 전부 동작한다.
import type {
  Action,
  Api,
  ChatMessage,
  MyRecipeDetail,
  MyRecipeInput,
  MyRecipeSummary,
  RecipeView,
  Screen,
  State,
} from "../types";
import { getAccessToken } from "./auth";
import { ApiError } from "./errors";

interface StoredRecipe {
  recipe_id: string;
  dish_name: string;
  ingredients: string[];
  instructions: string[];
  created_at: string;
  audio_ready: boolean;
}

const STANDARD: Record<string, { ingredients: string[]; steps: string[] }> = {
  된장찌개: {
    ingredients: ["두부", "감자", "애호박", "양파", "된장", "멸치 육수"],
    steps: [
      "두부와 감자, 애호박을 깍둑썰기 해 주세요.",
      "냄비에 멸치 육수를 붓고 된장을 풀어 주세요.",
      "국물이 끓으면 감자와 양파를 먼저 넣어 주세요.",
      "감자가 반쯤 익으면 애호박과 두부를 넣어 주세요.",
      "5분 정도 더 끓여 간을 맞춰 주세요.",
      "불을 끄고 그릇에 담아 내 주세요.",
    ],
  },
  김치볶음밥: {
    ingredients: ["밥", "김치", "대파", "달걀", "식용유"],
    steps: [
      "김치와 대파를 잘게 썰어 주세요.",
      "기름을 두른 팬에 대파를 볶아 향을 내 주세요.",
      "김치를 넣고 2분 정도 볶아 주세요.",
      "밥을 넣고 고루 섞으며 볶아 주세요.",
      "달걀프라이를 올려 완성해 주세요.",
    ],
  },
};

let recipes: StoredRecipe[] = [
  {
    recipe_id: "mock-r1",
    dish_name: "문어초무침",
    ingredients: ["문어", "오이", "초고추장"],
    instructions: ["문어를 데쳐 한입 크기로 썰어 주세요.", "오이와 초고추장에 버무려 주세요."],
    created_at: "2026-10-01T09:00:00Z",
    audio_ready: true,
  },
];

interface Sess {
  id: string;
  screen: Screen;
  /** unclassified 에서 돌아갈 화면 */
  back: Screen;
  dish: string | null;
  step: number;
  chat: ChatMessage[];
  reg: { dish_name: string | null; ingredients: string[]; instructions: string[]; guess: string | null };
}

const sessions = new Map<string, Sess>();
let counter = 1;

const delay = (ms = 250) => new Promise<void>((r) => window.setTimeout(r, ms));
const loggedIn = () => getAccessToken() !== null;

function recipeFor(s: Sess): RecipeView | null {
  if (!s.dish) return null;
  const std = STANDARD[s.dish];
  const own = recipes.find((r) => r.dish_name === s.dish);
  const ingredients = std?.ingredients ?? own?.ingredients ?? [];
  const texts = std?.steps ?? own?.instructions ?? [];
  const steps = texts.map((text, i) => ({ step_number: i + 1, text }));
  return {
    recipe_id: own?.recipe_id ?? `mock-std-${s.dish}`,
    dish_name: s.dish,
    ingredients,
    steps,
    step_number: Math.min(Math.max(s.step, 1), Math.max(steps.length, 1)),
    total: steps.length,
  };
}

function build(s: Sess, speech: string | null, extra: { notice?: string | null; transcript?: string | null } = {}): State {
  const showRecipe = ["recipe_confirm", "cooking_step", "cooking_complete", "unclassified", "complete"].includes(s.screen);
  const showReg = s.screen.startsWith("register_") || s.screen === "complete";
  return {
    session_id: s.id,
    screen: s.screen,
    logged_in: loggedIn(),
    transcript: extra.transcript ?? null,
    speech: speech ? { text: speech, audio_url: null } : null,
    notice: extra.notice ?? null,
    chat: s.chat.slice(-8),
    recipe: showRecipe ? recipeFor(s) : null,
    registration: showReg ? { ...s.reg, ingredients: [...s.reg.ingredients], instructions: [...s.reg.instructions] } : null,
  };
}

function ai(s: Sess, text: string): string {
  s.chat.push({ role: "ai", text });
  return text;
}

function resetToStart(s: Sess) {
  s.screen = "start";
  s.dish = null;
  s.step = 1;
  s.reg = { dish_name: null, ingredients: [], instructions: [], guess: null };
}

function stepSpeech(s: Sess): string {
  const r = recipeFor(s);
  const step = r?.steps[s.step - 1];
  return step ? `${s.step}단계, ${step.text}` : "1단계 정보를 찾지 못했어요.";
}

function startMessage(): string {
  return "무엇을 만들고 싶으세요? 하고 싶은 말을 편하게 말씀해주세요.";
}

function findDish(text: string): string | null {
  const compact = text.replace(/\s+/g, "");
  for (const name of [...Object.keys(STANDARD), ...recipes.map((r) => r.dish_name)]) {
    if (compact.includes(name.replace(/\s+/g, ""))) return name;
  }
  return null;
}

function goLoginRequired(s: Sess): State {
  s.screen = "login_required";
  return build(s, ai(s, "로그인이 필요해요. 로그인하면 레시피를 등록할 수 있어요."));
}

function startRegistration(s: Sess, guess: string | null): State {
  if (!loggedIn()) return goLoginRequired(s);
  s.reg = { dish_name: null, ingredients: [], instructions: [], guess };
  s.screen = "register_dish_name";
  return build(s, ai(s, "어떤 요리인가요? 요리 이름을 말씀해주세요."));
}

function handleText(s: Sess, raw: string): State {
  const text = raw.trim();
  s.chat.push({ role: "user", text });
  const norm = text.replace(/[?!.\s]+$/g, "");
  const ctx = { transcript: text };
  const home = ["처음", "홈", "메인", "초기"].some((w) => norm.includes(w));
  const yes = ["응", "네", "좋", "그래", "시작", "진행", "할래"].some((w) => norm.includes(w));
  const no = ["아니", "싫", "말고", "별로", "취소"].some((w) => norm.includes(w));

  if (home) {
    resetToStart(s);
    return build(s, ai(s, startMessage()), ctx);
  }

  let screen = s.screen;
  if (screen === "unclassified") screen = s.back;

  switch (screen) {
    case "start":
    case "complete":
    case "cooking_complete":
    case "login_required":
    case "my_recipes":
    case "edit_recipe": {
      if (norm.includes("등록")) return { ...startRegistration(s, null), transcript: text };
      const dish = findDish(norm);
      if (dish) {
        s.dish = dish;
        s.step = 1;
        s.screen = "recipe_confirm";
        return build(s, ai(s, `${dish}, 표준 레시피예요. 이걸로 시작할까요?`), ctx);
      }
      s.screen = "start";
      return build(
        s,
        ai(s, "등록되지 않은 레시피예요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요."),
        ctx,
      );
    }
    case "recipe_confirm": {
      if (norm.includes("등록")) return { ...startRegistration(s, null), transcript: text };
      if (norm.includes("다시")) return build(s, ai(s, `${s.dish}, 표준 레시피예요. 이걸로 시작할까요?`), ctx);
      if (no) {
        resetToStart(s);
        return build(s, ai(s, startMessage()), ctx);
      }
      if (yes || norm.includes("다음")) {
        s.screen = "cooking_step";
        s.step = 1;
        return build(s, ai(s, stepSpeech(s)), ctx);
      }
      s.back = "recipe_confirm";
      s.screen = "unclassified";
      return build(s, ai(s, "죄송해요, 잘 이해하지 못했어요. 다시 한 번 말씀해주시겠어요?"), ctx);
    }
    case "cooking_step": {
      if (norm.includes("다음")) return nav(s, "다음", ctx);
      if (norm.includes("다시")) return nav(s, "다시", ctx);
      if (norm.includes("이전")) return nav(s, "이전", ctx);
      s.back = "cooking_step";
      s.screen = "unclassified";
      return build(s, ai(s, "죄송해요, 잘 이해하지 못했어요. 다시 한 번 말씀해주시겠어요?"), ctx);
    }
    case "register_dish_name": {
      if (no) {
        resetToStart(s);
        return build(s, ai(s, startMessage()), ctx);
      }
      return dishNameChosen(s, text, ctx);
    }
    case "register_ingredients": {
      const items = text.split(",").map((x) => x.trim()).filter(Boolean);
      s.reg.ingredients.push(...items);
      return build(s, ai(s, `${items.join(", ")}, 추가했어요. 더 있으면 말씀해 주세요.`), ctx);
    }
    case "register_steps": {
      s.reg.instructions.push(text);
      return build(s, ai(s, "순서를 추가했어요. 더 있으면 말씀해 주세요."), ctx);
    }
    default:
      return build(s, null, ctx);
  }
}

function dishNameChosen(s: Sess, value: string, ctx: { transcript?: string | null } = {}): State {
  const v = value.trim();
  const confirm = ["네", "응", "맞아", "맞아요", "그래", "좋아"].includes(v);
  const name = confirm ? s.reg.guess : v;
  if (!name) return build(s, ai(s, "요리 이름을 다시 말씀해주세요."), ctx);
  s.reg.dish_name = name;
  s.screen = "register_ingredients";
  return build(s, ai(s, `${name}, 재료를 알려주세요.`), ctx);
}

function nav(s: Sess, name: "이전" | "다시" | "다음", ctx: { transcript?: string | null } = {}): State {
  const total = recipeFor(s)?.total ?? 0;
  s.screen = "cooking_step";
  if (name === "다음") {
    if (s.step >= total) {
      s.screen = "cooking_complete";
      return build(s, ai(s, "요리가 완성됐어요! 수고하셨어요."), ctx);
    }
    s.step += 1;
  } else if (name === "이전") {
    if (s.step <= 1) return build(s, ai(s, "1단계예요, 이전 단계가 없어요."), ctx);
    s.step -= 1;
  }
  return build(s, ai(s, stepSpeech(s)), ctx);
}

function handleAction(s: Sess, a: Action): State {
  switch (a.type) {
    case "nav":
      return nav(s, a.name);
    case "goto_step": {
      s.step = a.step_number;
      s.screen = "cooking_step";
      return build(s, ai(s, stepSpeech(s)));
    }
    case "start_cooking":
      s.screen = "cooking_step";
      s.step = 1;
      return build(s, ai(s, stepSpeech(s)));
    case "other_recipe":
    case "home":
    case "cancel":
      resetToStart(s);
      return build(s, ai(s, startMessage()));
    case "register_start":
      return startRegistration(s, null);
    case "register_dish_name":
      return dishNameChosen(s, a.value);
    case "register_add_ingredients": {
      s.reg.ingredients.push(...a.items.map((x) => x.trim()).filter(Boolean));
      return build(s, null);
    }
    case "register_ingredients_done":
      if (s.reg.ingredients.length === 0) return build(s, null, { notice: "재료를 하나 이상 추가해 주세요." });
      s.screen = "register_steps";
      return build(s, ai(s, "조리 순서를 알려주세요."));
    case "register_add_step":
      if (a.text.trim()) s.reg.instructions.push(a.text.trim());
      return build(s, null);
    case "register_edit_step":
      if (s.reg.instructions[a.index] !== undefined && a.text.trim()) s.reg.instructions[a.index] = a.text.trim();
      return build(s, null);
    case "register_delete_step":
      s.reg.instructions.splice(a.index, 1);
      return build(s, null);
    case "register_save": {
      if (!loggedIn()) return goLoginRequired(s);
      if (!s.reg.dish_name || s.reg.instructions.length === 0) {
        return build(s, null, { notice: "조리 순서를 하나 이상 추가해 주세요." });
      }
      recipes = [
        {
          recipe_id: `mock-r${++counter}`,
          dish_name: s.reg.dish_name,
          ingredients: [...s.reg.ingredients],
          instructions: [...s.reg.instructions],
          created_at: new Date().toISOString(),
          audio_ready: false,
        },
        ...recipes,
      ];
      s.dish = s.reg.dish_name; // 실제 서버처럼 저장 직후 화면에 방금 만든 레시피의 id 를 실어 보낸다
      s.screen = "complete";
      return build(s, ai(s, "저장이 완료됐어요!"));
    }
  }
}

function requireLogin() {
  if (!loggedIn()) {
    throw new ApiError(401, "로그인이 필요해요.");
  }
}

function getSess(id: string): Sess {
  const s = sessions.get(id);
  if (!s) {
    throw new ApiError(404, "세션을 찾을 수 없어요.");
  }
  return s;
}

const toDetail = (r: StoredRecipe): MyRecipeDetail => ({
  recipe_id: r.recipe_id,
  dish_name: r.dish_name,
  ingredients: [...r.ingredients],
  instructions: [...r.instructions],
});

export const mockApi: Api = {
  async warmup() {
    await delay(50);
  },
  async createSession() {
    await delay(400);
    const id = `mock-${Date.now().toString(36)}`;
    const s: Sess = {
      id,
      screen: "start",
      back: "start",
      dish: null,
      step: 1,
      chat: [],
      reg: { dish_name: null, ingredients: [], instructions: [], guess: null },
    };
    sessions.set(id, s);
    return build(s, ai(s, startMessage()));
  },
  async getSession(id) {
    await delay(150);
    return build(getSess(id), null);
  },
  async utteranceText(id, text) {
    await delay();
    return handleText(getSess(id), text);
  },
  async utteranceAudio(id) {
    await delay(500);
    return build(getSess(id), null, {
      notice: "데모 모드에서는 음성 인식이 동작하지 않아요. '말 대신 입력하기'나 버튼을 써 보세요.",
    });
  },
  async action(id, action) {
    await delay(150);
    return handleAction(getSess(id), action);
  },
  async tts() {
    throw new Error("mock tts 없음");
  },
  async listMyRecipes(): Promise<MyRecipeSummary[]> {
    await delay(200);
    requireLogin();
    // 데모: 만든 지 8초가 지나면 음성이 준비된 것으로 본다(실제 서버는 Modal GPU 가 끝낸 뒤).
    for (const r of recipes) if (!r.audio_ready && Date.now() - Date.parse(r.created_at) > 8000) r.audio_ready = true;
    return recipes.map(({ recipe_id, dish_name, created_at, audio_ready }) => ({
      recipe_id,
      dish_name,
      created_at,
      audio_ready,
    }));
  },
  async getMyRecipe(id) {
    await delay(150);
    requireLogin();
    const r = recipes.find((x) => x.recipe_id === id);
    if (!r) throw new ApiError(404, "레시피를 찾을 수 없어요.");
    return toDetail(r);
  },
  async updateMyRecipe(id, body: MyRecipeInput) {
    await delay(200);
    requireLogin();
    const r = recipes.find((x) => x.recipe_id === id);
    if (!r) throw new ApiError(404, "레시피를 찾을 수 없어요.");
    Object.assign(r, body, { audio_ready: false });
    return toDetail(r);
  },
  async deleteMyRecipe(id) {
    await delay(150);
    requireLogin();
    recipes = recipes.filter((x) => x.recipe_id !== id);
  },
};
