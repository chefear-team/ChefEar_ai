"""강사 체크리스트 4번 "백엔드 골격 — 가짜(mock) 응답을 먼저 돌려준다"용 가짜 Supabase 클라이언트.

## 왜 필요한가

지금 이 프로젝트는 Supabase 프로젝트 자체가 아직 없어서(자격증명 없음) 진짜 DB에
연결할 수가 없다. 그렇다고 오케스트레이션 함수들(recipe_search.py, pipeline.py 등)을
완성해놓고도 아무도 눈으로 결과를 못 보는 채로 기다리는 건 손해다 — UI 담당자가
화면을 이어붙여보거나, 발표용으로 미리 흐름을 시연해보려면 "그럴듯한 가짜 데이터"라도
지금 당장 리턴해줄 무언가가 필요하다.

그래서 진짜 supabase-py 클라이언트와 겉모습(메서드 이름, 체이닝 방식)이 완전히 같은
가짜 클라이언트를 만들고, DB 자격증명이 없을 때 db.get_client()가 자동으로 이걸
대신 돌려주게 만들었다. recipe_search.py 등의 코드는 한 줄도 안 바꿔도 된다 —
클라이언트가 진짜인지 가짜인지 구분하지 않고 그냥 .table("recipes").select(...)
같은 동일한 방식으로 부르기 때문이다(테스트에서 쓰던 tests/fake_supabase.py와
같은 설계 원리, "덕 타이핑". 사실 이 파일이 그 엔진의 원본이고, 테스트 쪽은
이 파일을 그대로 가져다 쓴다).

## 진짜 DB랑 다른 점

- 서버를 껐다 켜면(프로세스가 새로 시작되면) 가짜 데이터도 초기 시드 상태로 리셋된다
  (진짜 DB처럼 영구 저장이 아니라 파이썬 메모리에만 있음).
- 아래 시드 데이터는 문서 5장 시나리오(된장찌개 진행 중 "바지락 넣어도 돼?")를
  그대로 재현할 수 있게 일부러 골랐다 — 데모/발표에서 바로 그 대화를 보여줄 수 있다.
"""
from __future__ import annotations

import uuid


class FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Not:
    def __init__(self, query):
        self.query = query

    def ilike(self, col, pattern):
        self.query.filters.append(("not_ilike", col, pattern))
        return self.query


class FakeQuery:
    """진짜 supabase-py의 쿼리 빌더처럼 .eq().ilike()...를 체이닝할 수 있게 만든
    가짜 쿼리 객체. 조건을 filters 리스트에 쌓아두기만 하다가, execute()가
    호출될 때 비로소 테이블의 모든 행을 순회하며 조건에 맞는 것만 골라낸다.
    """

    def __init__(self, table, op="select", payload=None):
        self.table = table
        self.op = op
        self.payload = payload
        self.filters = []
        self.order_col = None
        self.want_single = False
        self.select_count = None
        self.range_bounds = None

    def select(self, *args, count=None):
        self.op = "select"
        self.select_count = count
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, values):
        self.filters.append(("in", col, values))
        return self

    def ilike(self, col, pattern):
        self.filters.append(("ilike", col, pattern))
        return self

    @property
    def not_(self):
        return _Not(self)

    def order(self, col):
        self.order_col = col
        return self

    def range(self, start: int, end: int):
        # 진짜 supabase-py(PostgREST)의 .range(start, end)를 흉내 낸다 — start/end
        # 둘 다 포함(inclusive)하는 구간만 남긴다. 실제 Supabase가 select() 결과를
        # 기본 1000행으로 자르는 것과 같은 동작을 재현해야, _all_dish_names()의
        # 페이지네이션 루프를 목업 클라이언트로도 똑같이 테스트할 수 있다.
        self.range_bounds = (start, end)
        return self

    def single(self):
        self.want_single = True
        return self

    def _match(self, row) -> bool:
        for kind, col, val in self.filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "in" and row.get(col) not in val:
                return False
            if kind == "ilike" and val.strip("%").lower() not in str(row.get(col, "")).lower():
                return False
            if kind == "not_ilike" and val.strip("%").lower() in str(row.get(col, "")).lower():
                return False
        return True

    def execute(self):
        if self.op == "insert":
            inserted = []
            for item in self.payload:
                row = dict(item)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("view_count", 0)
                row.setdefault("created_at", "")
                row.setdefault("origin_id", None)
                self.table.rows[row["id"]] = row
                inserted.append(row)
            return FakeResult(inserted)

        rows = [r for r in self.table.rows.values() if self._match(r)]

        if self.op == "delete":
            for r in rows:
                del self.table.rows[r["id"]]
            return FakeResult(rows)

        if self.order_col:
            rows = sorted(rows, key=lambda r: r.get(self.order_col, 0))
        if self.range_bounds:
            start, end = self.range_bounds
            rows = rows[start : end + 1]
        if self.want_single:
            return FakeResult(rows[0] if rows else None)
        return FakeResult(rows, count=len(rows) if self.select_count else None)


class FakeTable:
    def __init__(self, name):
        self.name = name
        self.rows: dict[str, dict] = {}

    def seed(self, row: dict) -> dict:
        row = dict(row)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("view_count", 0)
        row.setdefault("created_at", "")
        row.setdefault("origin_id", None)
        self.rows[row["id"]] = row
        return row

    def select(self, *args, count=None):
        return FakeQuery(self).select(*args, count=count)

    def insert(self, payload):
        if isinstance(payload, dict):
            payload = [payload]
        return FakeQuery(self, op="insert", payload=payload)

    def delete(self):
        return FakeQuery(self, op="delete")


class FakeSupabaseClient:
    def __init__(self):
        self._tables: dict[str, FakeTable] = {}

    def table(self, name: str) -> FakeTable:
        return self._tables.setdefault(name, FakeTable(name))


def build_mock_client() -> FakeSupabaseClient:
    """문서 5장 시나리오 A/B를 그대로 시연할 수 있도록 예시 레시피 3개를 미리 채워둔
    가짜 클라이언트를 만든다. db.get_client()가 자격증명 없을 때 이걸 대신 쓴다.
    """
    client = FakeSupabaseClient()
    recipes = client.table("recipes")
    steps = client.table("recipe_steps")

    doenjang = recipes.seed(
        {
            "dish_name": "된장찌개",
            "ingredients": "[재료] 두부| 감자| 애호박| 양파| 대파 [육수] 멸치| 다시마 [양념] 된장| 고추장",
            "source": "api_standard",
            "view_count": 1403370,
        }
    )
    for i, text in enumerate(
        [
            "멸치와 다시마로 육수를 끓입니다.",
            "두부와 감자를 먹기 좋은 크기로 썰어 넣습니다.",
            "된장을 풀어줍니다.",
            "한소끔 끓이면 완성입니다.",
        ],
        start=1,
    ):
        steps.seed({"recipe_id": doenjang["id"], "step_number": i, "step_text": text, "source": "api_standard"})

    bajirak = recipes.seed(
        {
            "dish_name": "바지락된장찌개",
            "ingredients": "[재료] 바지락| 두부| 애호박| 양파 [양념] 된장",
            "source": "api_standard",
            "view_count": 52000,
        }
    )
    for i, text in enumerate(
        ["바지락 해감한 것을 준비합니다.", "육수에 바지락을 먼저 넣고 끓입니다.", "된장을 풀고 두부를 넣어 마무리합니다."],
        start=1,
    ):
        steps.seed({"recipe_id": bajirak["id"], "step_number": i, "step_text": text, "source": "api_standard"})

    # 6.4 문서의 실측 사례("새우+바지락" 요청 -> 이름 매칭 실패 -> 재료 내용 매칭 성공)를
    # 그대로 시연할 수 있도록, 이름에는 없지만 재료에는 새우/바지락이 둘 다 들어간 레시피.
    haemul = recipes.seed(
        {
            "dish_name": "해물된장찌개",
            "ingredients": "[재료] 새우| 바지락| 오징어| 두부| 애호박 [양념] 된장",
            "source": "api_standard",
            "view_count": 31000,
        }
    )
    for i, text in enumerate(
        ["해물을 손질해 준비합니다.", "육수에 해물을 넣고 끓입니다.", "된장을 풀고 채소를 넣어 마무리합니다."], start=1
    ):
        steps.seed({"recipe_id": haemul["id"], "step_number": i, "step_text": text, "source": "api_standard"})

    return client
