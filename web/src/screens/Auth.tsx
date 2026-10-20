import { useEffect, useRef, useState, type FormEvent } from "react";
import { Icon } from "../components/common";
import {
  emailLoginAvailable,
  googleAvailable,
  signInWithGoogle,
  signInWithPassword,
  signUpWithPassword,
} from "../lib/auth";
import { errorMessage } from "../lib/errors";

/** 구글 공식 색의 "G" 로고. */
function GoogleLogo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"
      />
      <path
        fill="#FBBC05"
        d="M10.5 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.9-6.1z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"
      />
    </svg>
  );
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  error?: string | null;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className={`input-wrap${error ? " invalid" : ""}`}>
        <input
          id={id}
          type={show ? "text" : "password"}
          maxLength={72}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-msg` : undefined}
        />
        <button
          type="button"
          className="eye"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "비밀번호 숨기기" : "비밀번호 보기"}
          aria-pressed={show}
        >
          <Icon name={show ? "eyeOff" : "eye"} size={18} />
        </button>
      </div>
      {error && (
        <p id={`${id}-msg`} className="field-msg error">
          {error}
        </p>
      )}
    </div>
  );
}

/** 아래에서 올라오는 시트. Esc·바깥 클릭·닫기 버튼으로 닫히고, 열려 있는 동안 뒤 화면은 스크롤되지 않는다. */
function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      className="sheet-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet-grip" aria-hidden="true" />
        <div className="sheet-head">
          <h2 className="auth-title">{title}</h2>
          <button ref={closeRef} type="button" className="sheet-close" onClick={onClose} aria-label="닫기">
            <Icon name="x" size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** 이메일로 계속하기: 로그인 / 회원가입을 알약 스위치로 오간다. */
function EmailSheet({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => emailRef.current?.focus(), []);

  const isSignup = mode === "signup";
  const emailErr = touched && !EMAIL_RE.test(email.trim()) ? "이메일 주소를 확인해 주세요." : null;
  const pwErr = touched && isSignup && password.length < 8 ? "비밀번호는 8자 이상이어야 해요." : null;
  const pw2Err = touched && isSignup && password2 !== password ? "비밀번호가 일치하지 않습니다." : null;

  const switchMode = (next: "login" | "signup") => {
    if (next === mode) return;
    setMode(next);
    setError(null);
    setTouched(false);
    setPassword("");
    setPassword2("");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    const addr = email.trim();
    if (!EMAIL_RE.test(addr) || !password) return;
    if (isSignup && (password.length < 8 || password !== password2)) return;
    setBusy(true);
    setError(null);
    try {
      if (isSignup) {
        const signedIn = await signUpWithPassword(addr, password);
        if (!signedIn) setSentTo(addr);
        else onClose();
      } else {
        await signInWithPassword(addr, password);
        onClose();
      }
    } catch (err) {
      setError(errorMessage(err, "로그인하지 못했어요."));
    } finally {
      setBusy(false);
    }
  };

  if (sentTo) {
    return (
      <Sheet title="메일을 확인해 주세요" onClose={onClose}>
        <div className="auth auth-done" role="status">
          <div className="lead-icon neutral" aria-hidden="true">
            <Icon name="mail" size={26} />
          </div>
          <p className="auth-sub">
            <strong>{sentTo}</strong>로 확인 메일을 보냈어요. 메일의 링크를 누르면 가입이 끝나요. 안 보이면 스팸함도 확인해
            주세요.
          </p>
          <button
            type="button"
            className="btn lg primary"
            onClick={() => {
              setSentTo(null);
              switchMode("login");
            }}
          >
            로그인으로 돌아가기
          </button>
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet title="이메일로 계속하기" onClose={onClose}>
      <div className="auth">
        <div className="segmented" role="tablist" aria-label="로그인 또는 회원가입">
          <span className={`seg-thumb ${isSignup ? "right" : ""}`} aria-hidden="true" />
          <button type="button" role="tab" aria-selected={!isSignup} className="seg" onClick={() => switchMode("login")}>
            로그인
          </button>
          <button type="button" role="tab" aria-selected={isSignup} className="seg" onClick={() => switchMode("signup")}>
            회원가입
          </button>
        </div>

        <form className="auth-form" onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="auth-email">이메일</label>
            <div className={`input-wrap${emailErr ? " invalid" : ""}`}>
              <input
                ref={emailRef}
                id="auth-email"
                type="email"
                maxLength={254}
                inputMode="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
                aria-invalid={emailErr ? true : undefined}
                aria-describedby={emailErr ? "auth-email-msg" : undefined}
              />
            </div>
            {emailErr && (
              <p id="auth-email-msg" className="field-msg error">
                {emailErr}
              </p>
            )}
          </div>

          <PasswordField
            id="auth-pw"
            label={isSignup ? "비밀번호 (8자 이상)" : "비밀번호"}
            value={password}
            onChange={setPassword}
            autoComplete={isSignup ? "new-password" : "current-password"}
            error={pwErr}
          />
          {isSignup && (
            <PasswordField
              id="auth-pw2"
              label="비밀번호 확인"
              value={password2}
              onChange={setPassword2}
              autoComplete="new-password"
              error={pw2Err}
            />
          )}

          {error && (
            <p className="callout error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className={`btn xl primary${busy ? " loading" : ""}`} disabled={busy}>
            {busy && <span className="spinner" aria-hidden="true" />}
            <span>{isSignup ? "가입하고 시작하기" : "로그인"}</span>
          </button>
        </form>
      </div>
    </Sheet>
  );
}

/**
 * 로그인 화면: 구글 버튼 하나가 주인공이고, 이메일은 "다른 방법으로 계속하기"를 누르면 올라오는 시트로 처리한다.
 * 구글 버튼은 로그인과 가입을 겸한다(처음이면 계정이 만들어진다).
 */
export function LoginOptions() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);

  if (!googleAvailable && !emailLoginAvailable) {
    return <p className="faint">로그인 기능이 설정되지 않았어요. (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY)</p>;
  }

  const google = async () => {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle(); // 구글 화면으로 이동한다(돌아오면 로그인된 상태)
    } catch (e) {
      setError(errorMessage(e, "구글 로그인을 시작하지 못했어요."));
      setBusy(false);
    }
  };

  return (
    <div className="auth gate">
      {googleAvailable && (
        <button type="button" className={`google-btn big${busy ? " loading" : ""}`} disabled={busy} onClick={() => void google()}>
          {busy ? <span className="spinner" aria-hidden="true" /> : <GoogleLogo />}
          <span>{busy ? "구글로 이동하는 중..." : "구글로 계속하기"}</span>
        </button>
      )}
      {emailLoginAvailable && (
        <button type="button" className="plain-link" onClick={() => setSheet(true)}>
          다른 방법으로 계속하기
        </button>
      )}
      {error && (
        <p className="callout error" role="alert">
          {error}
        </p>
      )}
      {sheet && <EmailSheet onClose={() => setSheet(false)} />}
    </div>
  );
}
