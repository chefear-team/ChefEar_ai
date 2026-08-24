"""작업3 — 쿠키 기반 익명 UUID 개인화(FR-08). 로그인 기능은 없다.

왜 로그인 대신 쿠키인가: 이 프로젝트는 "누가 로그인했는지"를 몰라도, 그냥
"같은 브라우저로 다시 왔다"는 사실만 알면 충분하다(회원가입 없이 내가 등록한
레시피를 다음에 또 보고 싶은 것뿐이므로). 그래서 서버가 사용자 계정을 관리하는
대신, 브라우저 쿠키에 임의의 UUID(범용 고유 식별자, 예: "3fa8...-...")를 하나
심어두고, 그 값을 recipes 테이블의 owner_id 컬럼과 비교해서 "이건 내 레시피"
"이건 남의 레시피"를 구분한다.

streamlit-cookies-manager 라이브러리로 브라우저 쿠키를 읽고 쓴다. Streamlit은
서버(Python)와 브라우저(JS)가 분리돼 있어서 보통의 request.cookies처럼 바로
접근할 수 없고, 이 라이브러리가 JS 컴포넌트를 통해 쿠키 값을 Python 쪽으로
가져와준다.
"""
from __future__ import annotations

import logging
import os
import uuid

COOKIE_KEY = "chefear_anon_id"  # 브라우저에 저장될 쿠키의 이름(키)


class _SuppressStCacheDeprecation(logging.Filter):
    """streamlit-cookies-manager==0.2.0이 내부적으로 옛날 @st.cache를 그대로 써서
    (라이브러리 코드, 우리 코드 아님) 매 실행마다 뜨는 "st.cache is deprecated..."
    경고만 콘솔에서 숨긴다. 실제 동작엔 영향 없는 순수 deprecation 알림이라 무해함.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "`st.cache` is deprecated" not in record.getMessage()


logging.getLogger("streamlit.deprecation_util").addFilter(_SuppressStCacheDeprecation())


def get_or_create_anon_id(cookies) -> str:
    """쿠키에 이미 UUID가 있으면 그대로 쓰고, 없으면 새로 만들어서 저장한다.

    cookies 인자는 streamlit_cookies_manager의 CookieManager/EncryptedCookieManager
    객체를 기대하지만, 사실 아래 3가지 동작만 하면 무엇이든 대신 쓸 수 있다:
      1) cookies.get(key)      -> 값 조회(없으면 None)
      2) cookies[key] = value  -> 값 저장
      3) cookies.save()        -> 저장한 값을 실제로 브라우저에 반영(flush)
    이렇게 "필요한 동작만 갖춘 아무 객체"를 넣을 수 있게 만들어두면, 테스트에서는
    진짜 브라우저 없이 파이썬 dict 하나로도 이 함수를 검증할 수 있다
    (tests/test_identity.py의 FakeCookies 참고). 이런 설계를 보통
    "의존성 주입(dependency injection)"이라고 부른다.
    """
    existing = cookies.get(COOKIE_KEY)
    if existing:
        return existing  # 이미 발급된 쿠키가 있으면 그대로 재사용(새로 발급하지 않음)

    new_id = str(uuid.uuid4())  # uuid4()는 완전 무작위 UUID를 만들어준다
    cookies[COOKIE_KEY] = new_id
    cookies.save()  # save()를 안 부르면 브라우저에 실제로 반영되지 않는다
    return new_id


def build_cookie_manager():
    """실제 Streamlit 앱(src/app.py 등 UI 레이어)에서 쓸 EncryptedCookieManager를 만든다.

    "Encrypted"인 이유: 쿠키 값은 사용자 브라우저에 그대로 저장되기 때문에,
    사용자가 마음만 먹으면 개발자 도구로 열어볼 수 있다. UUID 자체는 민감한
    정보가 아니라서 암호화가 필수는 아니지만, 이 라이브러리가 기본으로
    암호화 버전을 제공해서 그대로 쓴다. 암호화에 필요한 비밀키가 COOKIE_SECRET
    환경변수다(.env.example.local 참고, 실제 값은 .env에만 적어야 한다).

    이 함수는 Streamlit이 실제로 스크립트를 실행하는 컨텍스트 안에서만 의미가
    있다(그냥 파이썬 콘솔에서 불러도 객체는 만들어지지만 쿠키를 읽어오지 못한다).
    호출하는 쪽(UI 코드)은 아래처럼 써야 한다:

        cookies = build_cookie_manager()
        if not cookies.ready():
            # 컴포넌트가 브라우저와 아직 통신 중 -> 이번 실행은 여기서 멈추고
            # 다음 rerun 때 다시 시도한다(Streamlit 특유의 패턴).
            st.stop()
        anon_id = get_or_create_anon_id(cookies)
        st.session_state["owner_id"] = anon_id  # 이후 요청들은 session_state에서 꺼내 씀
    """
    import streamlit as st

    # streamlit_cookies_manager.encrypted_cookie_manager가 옛날 @st.cache로 함수를
    # 감싸놓은 탓에, 이 모듈을 맨 처음 import하는 순간(데코레이터가 적용되는 시점)
    # Streamlit이 "st.cache is deprecated..." 경고를 st.warning()으로 화면에도 띄운다
    # (라이브러리 코드라 우리가 못 고침, 위 로깅 필터는 콘솔 출력만 막아서 화면 표시는
    # 못 막았음). import하는 그 순간만 st.warning을 무력화해서 화면에도 안 뜨게 한다 —
    # 모듈은 최초 1회만 import되므로 이후 다른 st.warning 호출엔 영향 없다.
    _original_warning = st.warning
    st.warning = lambda *args, **kwargs: None
    try:
        from streamlit_cookies_manager import EncryptedCookieManager
    finally:
        st.warning = _original_warning

    password = os.environ.get("COOKIE_SECRET")
    if not password:
        raise RuntimeError("COOKIE_SECRET이 .env에 없음 (쿠키 암호화 비밀키)")
    return EncryptedCookieManager(prefix="chefear/", password=password)
