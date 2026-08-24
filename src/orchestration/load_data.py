"""요리명별_조리과정 CSV -> Supabase recipes/recipe_steps 적재 (PRD 6.1, 6.2, 6.7).

## 이 스크립트가 하는 일 (전체 그림)

원본 CSV 한 줄은 이런 컬럼들을 갖고 있다: 요리명(CKG_NM), 재료(CKG_MTRL_CN),
조회수(INQ_CNT), 조리순서(COOKING_STEPS, "1. ...\\n2. ..." 형태의 긴 문자열),
등록일(FIRST_REG_DT) 등등. 이걸 우리 DB의 두 테이블로 옮겨야 한다.
  - recipes      : 요리 하나당 한 행 (요리명, 재료, 조회수, ...)
  - recipe_steps : 요리 하나에 여러 행 (1단계 텍스트, 2단계 텍스트, ...)

그래서 흐름은 "① CSV를 읽어서 표준 레시피만 골라내고 -> ② recipes에 넣고
그 결과로 받은 recipe_id를 기억해뒀다가 -> ③ 그 recipe_id를 이용해
recipe_steps에 단계별로 넣는다" 순서로 짜여 있다(run() 함수의 [1/4]~[4/4]
출력이 이 순서를 그대로 보여준다).

표준 레시피 선정 규칙(6.1): 같은 요리명(CKG_NM)이 CSV에 여러 번 나오면
조회수(INQ_CNT)가 제일 높은 행 하나만 채택한다 — 예를 들어 "된장찌개"라는
이름의 레시피가 여러 사람이 올린 게 섞여 있으면, 그중 제일 조회수 높은
것만 "표준"으로 쓴다는 뜻. source 컬럼은 항상 api_standard로 채운다
(사용자가 나중에 직접 등록하는 user_custom과 구분하기 위해).

사용법:
    python src/orchestration/load_data.py --csv <CSV 경로>
    python src/orchestration/load_data.py --csv <CSV 경로> --dry-run   # DB 연결 없이 파싱만 검증

CSV_NM/CKG_MTRL_CN/COOKING_STEPS 3개 컬럼만 있는 축약 CSV(예: 전처리 완료본으로
INQ_CNT/FIRST_REG_DT가 빠진 파일)도 그대로 넣을 수 있다 — 없는 컬럼은 그냥
DB 기본값(view_count=0, created_at=now())으로 채워진다(select_standard_rows,
build_recipe_payload 참고). 재실행 시 기존 api_standard 레코드를 먼저 삭제하고
다시 넣으므로([2/4] 단계), 이 스크립트를 다시 돌리는 것 자체가 "기존 표준
데이터 삭제 + 새 CSV 적재"다 — user_custom(사용자가 직접 등록한 레시피)은
건드리지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC = PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    # 이 스크립트를 `python src/orchestration/load_data.py`처럼 파일 경로로
    # 직접 실행하면, 파이썬은 이 파일이 있는 폴더(src/orchestration)만
    # import 검색 경로에 넣어준다. 그러면 뒤에서 쓸 `from orchestration.db
    # import get_client`가 실패한다(orchestration이라는 이름의 폴더를
    # src/orchestration 안에서는 찾을 수 없으니까). 그래서 한 단계 위인
    # src 폴더를 검색 경로에 직접 추가해준다.
    sys.path.insert(0, str(_SRC))
DEFAULT_CSV = PROJECT_ROOT / "data" / "standard" / "요리명별_조리과정_60282건.csv"
BATCH_SIZE = 500  # 한 번의 insert 요청에 몇 행씩 묶어 보낼지. 6만 건을 한 번에
# 보내면 요청이 너무 커지므로, 이 크기로 나눠서(chunked()) 여러 번 나눠 보낸다.

# "1. 문장내용" 형태의 한 줄을 (단계번호, 문장) 으로 뽑아내는 정규식.
# re.S(DOTALL) 옵션은 .가 줄바꿈 문자까지 포함해서 매칭하게 해준다.
STEP_LINE_RE = re.compile(r"^(\d+)\.\s*(.+)$", re.S)
# CSV의 FIRST_REG_DT 컬럼 형식("20170912232340.0" 같은 "YYYYMMDDHHMMSS.0")을 잡아내는 정규식.
FIRST_REG_DT_RE = re.compile(r"^(\d{14})\.0$")


def parse_first_reg_dt(raw: str) -> str:
    """"20170912232340.0" 같은 원본 날짜 문자열을 ISO 형식으로 바꾼다.

    형식이 예상과 다르면(파싱 실패) 그냥 지금 시각(UTC now)으로 대체한다 —
    날짜 하나 때문에 적재 전체를 실패시키지 않으려는 방어적 처리다.
    """
    m = FIRST_REG_DT_RE.match(raw.strip())
    if not m:
        return datetime.utcnow().isoformat()

    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return datetime.utcnow().isoformat()


def parse_steps(raw: str) -> list[str]:
    """COOKING_STEPS 컬럼(예: "1. 손질한다\\n2. 끓인다\\n3. ...")을 줄 단위로
    쪼개서 번호를 떼어낸 순수 문장 리스트로 만든다.

    예) "1. 닭을 손질해주세요.\\n2. 감자를 썰어주세요." ->
        ["닭을 손질해주세요.", "감자를 썰어주세요."]

    이렇게 번호를 미리 떼어내는 이유: recipe_steps 테이블에는 이미
    step_number라는 별도 컬럼이 있어서, 텍스트 안에 "1. "이 또 들어있으면
    "1. 1. 닭을 손질해주세요."처럼 중복돼 보기 안 좋기 때문이다.
    """
    texts = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = STEP_LINE_RE.match(line)
        texts.append(m.group(2).strip() if m else line)  # 번호 패턴이 안 맞으면 원문 그대로 둠(방어적 처리)
    return texts


def select_standard_rows(csv_path: Path) -> dict[str, dict]:
    """6.1 규칙: 동일 CKG_NM 다건 시 INQ_CNT 1위 채택 (동률이면 먼저 나온 행 유지).

    winners 딕셔너리의 키는 요리명, 값은 "지금까지 본 것 중 조회수가 제일
    높았던 행"이다. CSV를 한 줄씩 읽으면서, 이미 같은 요리명을 본 적 있으면
    조회수를 비교해서 더 높을 때만 교체한다 — 이게 바로 "동일 요리명 다건 시
    조회수 1위 채택"을 코드로 옮긴 것이다. 전체 CSV를 다 읽고 나면 winners에는
    요리명마다 딱 하나, 제일 조회수 높은 행만 남는다.

    INQ_CNT 컬럼이 아예 없는 CSV(예: 요리명별_조리과정_전처리완료_2.csv처럼
    이미 표준선정이 끝난 상태로 CKG_NM/CKG_MTRL_CN/COOKING_STEPS 3개 컬럼만
    남긴 축약 파일)도 그대로 지원한다 — row.get()으로 없으면 0 취급한다. 이런
    파일은 애초에 요리명 중복이 없는 전제라(이미 한 번 골라진 상태), 조회수를
    전부 0으로 봐도 최종 결과(요리명당 1행)는 똑같다.
    """
    winners: dict[str, dict] = {}
    with csv_path.open(encoding="utf-8-sig") as f:  # utf-8-sig: 엑셀이 저장한 BOM(파일 맨 앞의 보이지 않는 표시)을 자동으로 무시
        reader = csv.DictReader(f)  # 첫 줄을 헤더로 보고, 이후 각 줄을 {컬럼명: 값} 딕셔너리로 돌려줌
        for row in reader:
            name = row["CKG_NM"].strip()
            if not name:
                continue  # 요리명이 빈 값인 이상한 행은 건너뜀
            inq = int(row["INQ_CNT"]) if row.get("INQ_CNT") else 0
            current = winners.get(name)
            current_inq = int(current["INQ_CNT"]) if current and current.get("INQ_CNT") else 0
            if current is None or inq > current_inq:
                winners[name] = row
    return winners


def chunked(seq: list, size: int):
    """리스트를 size개씩 잘라서 순서대로 돌려주는 제너레이터.

    예) chunked([1,2,3,4,5], 2) -> [1,2], [3,4], [5] 를 순서대로 준다.
    Supabase에 한 번에 너무 많은 행을 insert하면 요청이 실패할 수 있어서,
    이렇게 작은 묶음으로 나눠 여러 번 보내려고 쓴다.
    """
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def build_recipe_payload(row: dict) -> dict:
    """CSV의 한 행(딕셔너리)을 recipes 테이블에 그대로 넣을 수 있는 딕셔너리로 변환한다.

    INQ_CNT/FIRST_REG_DT가 없는 CSV(축약 전처리 파일)는 그 키를 payload에서
    아예 빼버린다 — insert할 때 그 컬럼을 안 보내면 DB가 스스로 기본값
    (view_count=0, created_at=now(), schema.sql 참고)을 채워주므로, 여기서
    0이나 현재시각을 직접 흉내 낼 필요가 없다. external_id/servings는 기존
    코드에서도 채운 적이 없는 미사용 컬럼이라(코드 전체 검색 결과 참조하는
    곳이 없음) 여기서도 그대로 안 채운다.
    """
    payload = {
        "dish_name": row["CKG_NM"].strip(),
        "ingredients": row["CKG_MTRL_CN"].strip(),
        "source": "api_standard",
        "origin_id": None,
    }
    if row.get("INQ_CNT"):
        payload["view_count"] = int(row["INQ_CNT"])
    if row.get("FIRST_REG_DT"):
        payload["created_at"] = parse_first_reg_dt(row["FIRST_REG_DT"])
    return payload


def run(csv_path: Path, dry_run: bool) -> None:
    """실제 적재 과정 전체. dry_run=True면 CSV 파싱까지만 하고 DB에는 손대지 않는다
    (Supabase 자격증명 없이도 로직이 맞는지 미리 확인할 수 있게 만든 옵션).
    """
    if not csv_path.exists():
        sys.exit(f"CSV 파일을 찾을 수 없음: {csv_path}")

    print(f"[1/4] CSV 파싱 및 6.1 표준선정 규칙 적용 중: {csv_path}")
    winners = select_standard_rows(csv_path)
    rows = list(winners.values())
    print(f"      -> 고유 요리명 {len(rows)}건 선정")

    total_steps = sum(len(parse_steps(row["COOKING_STEPS"])) for row in rows)
    print(f"      -> 총 조리순서(step) {total_steps}건")

    if dry_run:
        print("[dry-run] Supabase 연결/적재 생략, 파싱 결과만 확인함")
        return

    from orchestration.db import get_client

    try:
        # allow_mock=False: 이 스크립트는 실데이터 6만여 건을 "진짜로" 적재하는 게
        # 목적이라, 자격증명이 없다고 가짜 메모리에 조용히 적재해버리면 "성공했다"는
        # 착각만 준다. 그래서 여기만 예외적으로 mock 폴백을 막고 확실히 실패시킨다.
        client = get_client(allow_mock=False)
    except RuntimeError as e:
        sys.exit(str(e))

    # 이 스크립트를 여러 번 실행할 수도 있으므로(예: 나중에 전처리된 CSV로
    # 교체해서 다시 돌릴 때), 매번 새로 적재하기 전에 기존 api_standard
    # 데이터를 먼저 지운다. recipe_steps을 먼저 지우는 이유: recipe_steps의
    # recipe_id가 recipes.id를 참조하고 있어서(외래키), recipes를 먼저 지우면
    # 참조가 끊겨 에러가 날 수 있다 — 항상 "자식 테이블 먼저, 부모 테이블 나중"
    # 순서로 지워야 한다.
    print("[2/4] 기존 api_standard 레코드 삭제 (재실행 대비)")
    client.table("recipe_steps").delete().eq("source", "api_standard").execute()
    client.table("recipes").delete().eq("source", "api_standard").execute()

    print("[3/4] recipes 적재 중")
    dish_to_id: dict[str, str] = {}  # "요리명 -> 방금 DB가 발급해준 recipe_id" 를 기억해두는 표
    for batch in chunked(rows, BATCH_SIZE):
        payload = [build_recipe_payload(row) for row in batch]
        res = client.table("recipes").insert(payload).execute()
        # insert()의 결과(res.data)에는 방금 넣은 행들이 id까지 채워진 채로 돌아온다.
        # 이걸 dish_to_id에 기록해둬야, 바로 다음 단계에서 "이 요리의 조리순서를
        # recipe_steps에 넣을 때 recipe_id로 뭘 써야 하는지" 알 수 있다.
        for inserted in res.data:
            dish_to_id[inserted["dish_name"]] = inserted["id"]
        print(f"      -> {len(dish_to_id)}/{len(rows)}")

    print("[4/4] recipe_steps 적재 중")
    step_payload = []
    for row in rows:
        recipe_id = dish_to_id[row["CKG_NM"].strip()]  # 위에서 기억해둔 recipe_id를 꺼내 씀
        for i, text in enumerate(parse_steps(row["COOKING_STEPS"]), start=1):
            step_payload.append(
                {
                    "recipe_id": recipe_id,
                    "step_number": i,
                    "step_text": text,
                    "source": "api_standard",
                }
            )
    inserted_steps = 0
    for batch in chunked(step_payload, BATCH_SIZE):
        client.table("recipe_steps").insert(batch).execute()
        inserted_steps += len(batch)
        print(f"      -> {inserted_steps}/{len(step_payload)}")

    # 마지막으로 "진짜로 몇 건이 들어갔는지" DB에 직접 물어봐서 확인한다.
    # count="exact"를 select에 넘기면 행 데이터 대신(또는 함께) 정확한 개수를 세어준다.
    print("[검증] 행 수 확인")
    recipes_count = (
        client.table("recipes").select("id", count="exact").eq("source", "api_standard").execute().count
    )
    steps_count = (
        client.table("recipe_steps")
        .select("recipe_id", count="exact")
        .eq("source", "api_standard")
        .execute()
        .count
    )
    print(f"recipes(api_standard) = {recipes_count}")
    print(f"recipe_steps(api_standard) = {steps_count}")


def main() -> None:
    """터미널에서 이 스크립트를 실행했을 때의 진입점. --csv, --dry-run 같은
    커맨드라인 옵션을 해석해서 run()에 넘겨준다(argparse는 파이썬 표준
    커맨드라인 인자 파서다).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="요리명별_조리과정 CSV 경로")
    parser.add_argument("--dry-run", action="store_true", help="DB 연결 없이 파싱만 검증")
    args = parser.parse_args()
    run(args.csv, args.dry_run)


if __name__ == "__main__":
    # 이 파일을 직접 실행했을 때만(예: `python load_data.py`) main()이 돌고,
    # 다른 파일에서 `import load_data`로 불러올 땐 자동으로 실행되지 않는다.
    main()
