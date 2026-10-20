import { useEffect, useRef, useState } from "react";
import { MicBar, TextFallback } from "./components/Dock";
import { Icon, SlowBanner } from "./components/common";
import { ProcessingOverlay } from "./components/ProcessingOverlay";
import { MOCK } from "./config";
import { api } from "./lib/api";
import { signOut, useAuth } from "./lib/auth";
import { player, usePlayer } from "./lib/player";
import { useSession } from "./lib/useSession";
import { useVoice } from "./lib/useVoice";
import { EditRecipeScreen, LoginRequiredScreen, MyRecipesScreen } from "./screens/Account";
import {
  CookingCompleteScreen,
  CookingStepScreen,
  RecipeConfirmScreen,
  StartScreen,
  UnclassifiedScreen,
} from "./screens/Cooking";
import { Landing } from "./screens/Landing";
import {
  CompleteScreen,
  RegisterDishNameScreen,
  RegisterIngredientsScreen,
  RegisterStepsScreen,
} from "./screens/Register";
import type { Action, Screen } from "./types";

/** 서버 State.screen 과 별개로, 마이레시피 목록/수정/로그인은 REST 로 따로 그리는 화면이라 UI 쪽 라우팅만 둔다. */
type LocalView = { kind: "login" } | { kind: "my_recipes" } | { kind: "edit"; id: string };

/**
 * 마이크로 말을 받는 화면 = 조리 흐름. 레시피 등록(요리명·재료·순서·완료)과 마이레시피는 글자로 입력하므로
 * 이 화면들에서는 마이크 연결을 아예 닫는다(브라우저 마이크 표시등도 꺼진다). 조리 흐름으로 돌아오면 다시 연결한다.
 */
const VOICE_SCREENS: ReadonlySet<Screen> = new Set<Screen>([
  "start",
  "recipe_confirm",
  "cooking_step",
  "cooking_complete",
  "unclassified",
]);

/** 내용이 짧아 화면 세로 가운데에 두는 화면(원본의 시작·완료·인식 실패·등록 안내). */
const CENTERED_SCREENS: ReadonlySet<Screen> = new Set<Screen>([
  "start",
  "cooking_complete",
  "unclassified",
  "complete",
  "login_required",
]);

const MIC_HINT: Partial<Record<Screen, string>> = {
  start: "“된장찌개 어떻게 만들어?”처럼 말씀해주세요",
  recipe_confirm: "“응” 또는 다른 요청을 말씀해주세요",
  cooking_step: "“이전” · “다시” · “다음”",
  cooking_complete: "“처음으로”라고 말해도 돼요",
  unclassified: "다시 한번 말씀해주세요",
  register_dish_name: "요리 이름을 말씀해주세요",
  complete: "“처음으로”라고 말해도 돼요",
};

export default function App() {
  const auth = useAuth();
  const playerSnap = usePlayer();
  const [started, setStarted] = useState(false);
  const [local, setLocal] = useState<LocalView | null>(null);
  /** 말을 보내고 응답을 기다리는 중(오버레이·알림음 대상). 글자·버튼 요청은 포함하지 않는다. */
  const [voiceBusy, setVoiceBusy] = useState(false);

  const session = useSession({ onSpeech: (sp) => void player.speak(sp) });
  const { state } = session;

  // 서비스 전체가 로그인 전용이다(GPU 비용 보호, 서버도 같은 규칙으로 막는다). 로그인 전에는 로그인 화면만 나온다.
  const authed = auth.token !== null;
  const serverScreen = state?.screen ?? null;
  const voiceScreen = started && local === null && serverScreen !== null && VOICE_SCREENS.has(serverScreen);
  const gate = voiceScreen && !playerSnap.busy && !session.busy;

  const voice = useVoice({
    gate,
    onUtterance: (wav) => {
      setLocal(null);
      setVoiceBusy(true);
      void session.sendAudio(wav).finally(() => setVoiceBusy(false));
    },
  });

  const loggedIn = authed;
  /** 우상단 표시용 이름: 이메일이 길면 9자까지만(원본의 아이디 말줄임과 같다). */
  const userName = auth.email ? (auth.email.length > 9 ? `${auth.email.slice(0, 9)}…` : auth.email) : "내 계정";

  // ---- 시작하기 ----
  const onPrepare = () => {
    player.unlock(); // 클릭 안에서 동기로: 이후 자동 재생 허용
    voice.prepare();
  };
  const onStart = (withVoice = true) => {
    setStarted(true);
    session.enableSpeech();
    if (withVoice) void voice.enable();
  };
  /** 랜딩에서 바로 마이레시피로 들어간다(로그인한 경우). */
  const onOpenMyRecipes = () => {
    player.unlock();
    onPrepare();
    onStart(false); // 마이레시피는 글자 화면이라 마이크를 켜지 않는다
    setLocal({ kind: "my_recipes" });
  };

  // 말로 진행하는 화면에 들어오면 마이크를 연결하고, 글자로 입력하는 화면(등록·마이레시피)에서는 연결을 닫는다.
  const micNeeded = voiceScreen;
  useEffect(() => {
    if (!started || !authed) return;
    if (!micNeeded && voice.phase === "on") void voice.release();
    else if (micNeeded && voice.phase === "off" && !voice.muted) void voice.enable();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [micNeeded, voice.phase, started, authed]);

  // ---- 로그인·로그아웃 ----
  // 로그인하면 세션을 만들고(저장된 세션이 있으면 이어서) STT GPU 를 미리 깨운다.
  // 로그아웃하면 세션을 버리고 로그인 화면으로 돌아간다. 토큰이 갱신될 때마다가 아니라 로그인 여부가 바뀔 때만 동작한다.
  const prevAuthed = useRef<boolean | null>(null);
  useEffect(() => {
    if (!auth.ready) return;
    const before = prevAuthed.current;
    prevAuthed.current = authed;
    if (authed) {
      void api.warmup();
      void session.init();
    } else if (before === true) {
      // 로그아웃: 마이크 연결을 실제로 닫고(브라우저 표시등 꺼짐), 세션을 버리고, 로그인 화면으로 돌아간다.
      // 다시 로그인한 뒤 "시작하기"를 누르면 마이크가 새로 연결된다.
      void voice.disable();
      player.stop();
      setStarted(false);
      setLocal(null);
      session.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.ready, authed]);

  // 화면이 바뀌면 맨 위로
  const viewKey = local ? `local:${local.kind}` : `server:${serverScreen}`;
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [viewKey]);

  const act = (a: Action) => {
    setLocal(null);
    void session.act(a);
  };
  const say = (text: string) => {
    setLocal(null);
    void session.sayText(text);
  };
  const goHome = () => {
    setLocal(null);
    if (serverScreen !== null && serverScreen !== "start") void session.act({ type: "home" });
  };

  // ---------------- 화면 선택 ----------------
  const screenProps = state
    ? { state, act, onReplay: session.replay, onMyRecipes: loggedIn ? () => setLocal({ kind: "my_recipes" }) : undefined }
    : null;
  let body: React.ReactNode;
  let showDock = false;

  if (local?.kind === "login") {
    body = <LoginRequiredScreen onBack={goHome} onDone={() => undefined} />;
  } else if (local?.kind === "my_recipes") {
    body = (
      <MyRecipesScreen
        loggedIn={loggedIn}
        userName={userName}
        onLogout={() => void signOut()}
        onEdit={(id) => setLocal({ kind: "edit", id })}
        onBack={goHome}
        onLogin={() => setLocal({ kind: "login" })}
        onRegister={() => act({ type: "register_start" })}
      />
    );
  } else if (local?.kind === "edit") {
    body = <EditRecipeScreen id={local.id} onClose={() => setLocal({ kind: "my_recipes" })} />;
  } else if (!state || !screenProps) {
    body = (
      <div className="hero">
        {session.error ? (
          <div className="lead-icon warn" aria-hidden="true">
            <Icon name="x" size={26} />
          </div>
        ) : (
          <span className="spinner big" aria-hidden="true" />
        )}
        <h1>{session.error ? "서버에 연결하지 못했어요" : "준비하는 중이에요"}</h1>
        <p>{session.error ?? "서버와 연결하고 있어요..."}</p>
        {session.error && (
          <button type="button" className="btn xl primary" onClick={() => void session.init()}>
            다시 시도
          </button>
        )}
      </div>
    );
  } else {
    showDock = true;
    switch (state.screen) {
      case "start":
        body = <StartScreen {...screenProps} />;
        break;
      case "recipe_confirm":
        body = <RecipeConfirmScreen {...screenProps} />;
        break;
      case "cooking_step":
        body = <CookingStepScreen {...screenProps} />;
        break;
      case "cooking_complete":
        body = <CookingCompleteScreen {...screenProps} />;
        break;
      case "unclassified":
        body = <UnclassifiedScreen {...screenProps} />;
        break;
      case "register_dish_name":
        body = <RegisterDishNameScreen {...screenProps} />;
        break;
      case "register_ingredients":
        body = <RegisterIngredientsScreen {...screenProps} />;
        break;
      case "register_steps":
        body = <RegisterStepsScreen {...screenProps} />;
        break;
      case "complete":
        body = <CompleteScreen {...screenProps} />;
        break;
      case "login_required":
        showDock = false;
        body = <LoginRequiredScreen onBack={goHome} onDone={() => undefined} />;
        break;
      case "my_recipes":
      case "edit_recipe":
        showDock = false;
        body = (
          <MyRecipesScreen
            loggedIn={loggedIn}
        userName={userName}
        onLogout={() => void signOut()}
            onEdit={(id) => setLocal({ kind: "edit", id })}
            onBack={goHome}
            onLogin={() => setLocal({ kind: "login" })}
            onRegister={() => act({ type: "register_start" })}
          />
        );
        break;
      default:
        body = <StartScreen {...screenProps} />;
    }
  }

  if (!started) {
    return (
      <div className="app">
        <SlowBanner />
        <Landing onPrepare={onPrepare} onStart={onStart} onMyRecipes={onOpenMyRecipes} />
      </div>
    );
  }

  return (
    <div className="app">
      <SlowBanner />
      <header className="topbar">
        <button type="button" className="brand" onClick={goHome} aria-label="처음 화면으로">
          <img className="brand-logo" src="/brand/logo.png" alt="ChefEar" width={512} height={280} />
        </button>
        <nav className="topnav" aria-label="메뉴">
          <button
            type="button"
            className="account-btn"
            onClick={() => setLocal({ kind: "my_recipes" })}
            aria-label={`${userName}, 마이레시피 열기`}
          >
            <Icon name="user" size={16} />
            <span>{userName}</span>
          </button>
        </nav>
      </header>

      <main className="main" id="main">
        {MOCK && <p className="mockbar">데모 모드 (가짜 서버) · 음성 인식은 동작하지 않아요</p>}
        {session.error && state && (
          <div className="notice error" role="alert">
            <span>{session.error}</span>
            <button type="button" className="linkbtn" onClick={session.dismissError}>
              닫기
            </button>
          </div>
        )}
        {local === null && state?.notice && (
          <div className="notice" role="status">
            {state.notice}
          </div>
        )}
        {local === null && state?.transcript && <p className="heard">들은 말: “{state.transcript}”</p>}
        {/* 화면마다 key 가 달라 React 가 이전 화면의 DOM 을 통째로 버리고 새로 만든다(잔상이 남을 자리가 없다).
            서버 응답을 기다리는 동안엔 이전 화면을 흐리게 하고 눌리지 않게 해서 낡은 화면과 새 화면이 섞여 보이지 않게 한다. */}
        <div
          key={viewKey}
          className={`view${CENTERED_SCREENS.has(serverScreen as Screen) && local === null ? " centered" : ""}${session.busy && !voiceBusy ? " busy" : ""}`}
          aria-busy={session.busy}
        >
          {body}
        </div>
      </main>

      <ProcessingOverlay active={voiceBusy} />

      {showDock && (
        <footer className="dock">
          <MicBar
            phase={voice.phase}
            error={voice.error}
            muted={voice.muted}
            hearing={voice.hearing}
            listening={voice.listening}
            speaking={playerSnap.busy}
            blocked={playerSnap.blocked}
            processing={session.busy}
            voiceScreen={voiceScreen}
            hint={serverScreen ? (MIC_HINT[serverScreen] ?? "아래 입력창이나 버튼을 써 주세요") : ""}
            onToggleMute={voice.toggleMuted}
            onRetry={() => void voice.enable()}
            onReplay={session.replay}
          />
          <TextFallback onSend={say} />
        </footer>
      )}
    </div>
  );
}
