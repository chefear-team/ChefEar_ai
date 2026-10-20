import { DEMO_VIDEO_URL, MOCK } from "../config";
import { signOut, useAuth } from "../lib/auth";
import { LoginOptions } from "./Auth";

/** 유튜브/비메오 링크는 iframe 으로, 그 밖에는 <video> 로 보여 준다. */
function videoEmbed(url: string): { kind: "iframe" | "video"; src: string } {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    if (host === "youtu.be") return { kind: "iframe", src: `https://www.youtube.com/embed/${u.pathname.slice(1)}` };
    if (host.endsWith("youtube.com")) {
      if (u.pathname.startsWith("/embed/")) return { kind: "iframe", src: url };
      const id = u.searchParams.get("v");
      if (id) return { kind: "iframe", src: `https://www.youtube.com/embed/${id}` };
    }
    if (host === "vimeo.com" && /^\/\d+/.test(u.pathname)) {
      return { kind: "iframe", src: `https://player.vimeo.com/video${u.pathname}` };
    }
  } catch {
    /* 상대 경로 등은 그대로 video 로 */
  }
  return { kind: "video", src: url };
}

const STEPS = [
  { title: "말하기", say: "“된장찌개 어떻게 만들어?”", desc: "만들고 싶은 요리를 편하게 말해요." },
  { title: "확인하기", say: "“응”", desc: "표준 레시피가 맞으면 시작해요." },
  { title: "한 단계씩", say: "“다음”", desc: "“다시” “이전”도 말할 수 있어요. 손은 요리에 쓰세요." },
];

export function Landing({
  onPrepare,
  onStart,
  onMyRecipes,
}: {
  onPrepare: () => void;
  onStart: () => void;
  onMyRecipes: () => void;
}) {
  const auth = useAuth();
  const video = DEMO_VIDEO_URL ? videoEmbed(DEMO_VIDEO_URL) : null;

  // 오디오 잠금 해제는 클릭 핸들러 안에서 동기로 해야 하므로 onPrepare 를 먼저 부른다.
  const start = () => {
    onPrepare();
    onStart();
  };

  // 로그인 여부를 아직 모를 때(새로고침 직후)는 로그인 화면이 잠깐 번쩍이지 않게 기다린다.
  if (!auth.ready) {
    return (
      <div className="landing">
        <header className="landing-hero">
          <img className="landing-logo" src="/brand/logo.png" alt="ChefEar" width={512} height={280} />
          <span className="spinner big" aria-hidden="true" />
        </header>
      </div>
    );
  }

  return (
    <div className="landing">
      <header className="landing-hero">
        <h1 className="sr-only">셰프이어 ChefEar</h1>
        <img className="landing-logo" src="/brand/logo.png" alt="ChefEar — 당신의 AI 요리 파트너" width={512} height={280} />
        <p className="lead">손이 바쁜 요리 중에도, 말로 한 단계씩 레시피를 안내받는 음성 요리 도우미</p>
        {MOCK && <p className="callout">데모 모드예요. 서버 없이 화면 흐름만 눌러 볼 수 있어요. 음성 인식은 동작하지 않아요.</p>}

        {auth.token ? (
          <div className="stack">
            <button type="button" className="btn xl primary" onClick={start}>
              시작하기
            </button>
            <button type="button" className="btn lg" onClick={onMyRecipes}>
              내 레시피 보기
            </button>
            <p className="loginstate center">
              <span className="loginstate-dot" aria-hidden="true" />
              {auth.email ?? "로그인됨"} 로그인 중{" "}
              <button type="button" className="linkbtn" onClick={() => void signOut()}>
                로그아웃
              </button>
            </p>
            <p className="faint center">
              시작하면 마이크 사용 권한을 물어봐요. 마이크 없이도 글자 입력과 버튼으로 모두 쓸 수 있어요.
            </p>
          </div>
        ) : (
          <div className="stack">
            <LoginOptions />
            <p className="faint center small">로그인한 사용자만 쓸 수 있어요. 구글 계정이면 한 번에 시작돼요.</p>
          </div>
        )}
      </header>

      <section className="guide" aria-labelledby="guide-title">
        <h2 id="guide-title">이렇게 써 보세요</h2>
        <ol className="guide-steps">
          {STEPS.map((s, i) => (
            <li key={s.title} className="guide-step">
              <span className="guide-no">{i + 1}</span>
              <div>
                <strong>{s.title}</strong>
                <span className="say">{s.say}</span>
                <p>{s.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {video && (
        <section className="demo-video" aria-labelledby="video-title">
          <h2 id="video-title">데모 영상</h2>
          <div className="video-frame">
            {video.kind === "iframe" ? (
              <iframe
                src={video.src}
                title="셰프이어 데모 영상"
                loading="lazy"
                allow="accelerometer; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
              />
            ) : (
              <video src={video.src} controls preload="metadata" playsInline />
            )}
          </div>
        </section>
      )}

      <footer className="landing-foot faint">
        <p>첫 접속 때는 서버가 깨어나는 데 수십 초가 걸릴 수 있어요.</p>
      </footer>
    </div>
  );
}
