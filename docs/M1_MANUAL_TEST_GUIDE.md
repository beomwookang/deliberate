# M1 수동 테스트 가이드 — 구체적 실행 방법

> 자동 검증(`M1_VALIDATION_REPORT.md`)이 끝나고 Critical 이슈가 해결된 뒤에 진행.
> 이 가이드는 **사람만 판정 가능한 것**에 집중합니다.

---

## 사전 준비

터미널 2개 열어두기:
- **터미널 A**: 에이전트 실행용
- **터미널 B**: curl/확인용

```bash
# 터미널 A에 환경변수 세팅 (매번 필요)
cd examples/refund_agent
export DELIBERATE_SERVER_URL=http://localhost:4000
export DELIBERATE_API_KEY=SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs
export DELIBERATE_UI_URL=http://localhost:3000
```

Docker 확인:
```bash
curl http://localhost:4000/health
# {"status":"ok"} 나와야 함
```

---

## 2.1 — 30초 룰 테스트 (15분)

**목적**: 승인자가 페이지 열고 → 읽고 → 결정 → submit까지 30초 안에 되는가?

### 방법

1. 폰에 스톱워치 앱 열기 (또는 맥 시계 앱 타이머)

2. 터미널 A에서:
```bash
uv run python agent.py
```

3. `[DELIBERATE] Approval needed: http://localhost:3000/a/xxxxx` URL이 출력되면:
   - **스톱워치 시작**
   - 브라우저에서 URL 열기
   - 페이지를 읽기 (무슨 결정인지, 금액, 고객, 이유 확인)
   - 결정 버튼 클릭 (Approve/Reject 등)
   - rationale 선택 (선택사항)
   - Submit Decision 클릭
   - **스톱워치 정지**

4. 걸린 시간 기록하기. 예: "12초"

5. 터미널 A에서 에이전트가 완료되면 (`Agent completed.`) 다시 `uv run python agent.py` 실행

6. 이걸 **최소 5회, 이상적으로 10회** 반복

### 기록할 것
- 각 회차의 시간
- 평균 시간
- 30초 넘긴 회차가 있으면 — 왜? (정보 찾는 데 시간 걸렸나, 뭘 더 알고 싶었나)

### 판정 기준
- 평균 30초 이내면 OK
- 60초 넘으면 UI 재설계 필요

---

## 2.3 — 약한 증거 테스트 (15분)

**목적**: evidence가 빈약할 때도 승인자가 무조건 approve 누르지 않는지. UI가 비판적 사고를 유도하는지.

### 방법

1. `examples/refund_agent/agent.py`를 에디터로 열기

2. `classify` 함수의 return 값을 이렇게 바꾸기:
```python
def classify(state: RefundState) -> dict[str, Any]:
    logger.info("Classifying refund request for customer %s", state["customer_id"])
    return {
        "reasoning": "Customer seems unhappy. Refund recommended.",
        "evidence": [
            {
                "type": "complaint",
                "id": "#9999",
                "summary": "Customer complained once",
                "url": None,
            },
        ],
    }
```

3. 터미널 A에서 에이전트 실행:
```bash
uv run python agent.py
```

4. URL 열고 페이지를 보기. 이번엔 **일부러 천천히** 읽기.

5. 스스로에게 물어보기:
   - "이 정보만으로 $750 환불을 승인해도 되나?"
   - "더 알아야 할 게 있지 않나?"
   - Escalate (더 많은 정보 요청) 버튼이 매력적으로 보이나, 아니면 그냥 Approve가 편한가?

6. **솔직하게** 결정하기. 10회 중 몇 번 approve 했는지 기록.

7. 원래대로 `agent.py` 복원하기:
```bash
git checkout examples/refund_agent/agent.py
```

### 기록할 것
- 10번 중 approve 비율 (8/10이면 UI가 비판적 사고 유도 실패)
- "evidence가 약하다"는 게 시각적으로 눈에 띄었나?
- Escalate 버튼이 쓰기 편했나?

---

## 2.4 — 비엔지니어 테스트 (15분)

**목적**: 엔지니어가 아닌 사람(재무 담당자, 부모, 친구)이 이 페이지를 이해하고 결정할 수 있는가?

### 방법

1. 에이전트 실행해서 approval URL 하나 만들기:
```bash
uv run python agent.py
```

2. URL을 복사

3. **다른 사람**에게 노트북 건네기 (또는 폰으로 URL 공유)

4. 이 말만 하기: "이 페이지에서 결정 하나만 내려줘. 뭔지는 페이지에 다 써있어."

5. **관찰하기** (입 다물고 보기만):
   - 몇 초 만에 "아 이게 뭔지 알겠다" 반응이 오는가?
   - 어떤 부분을 먼저 보는가?
   - "이게 뭐야?" 하고 물어보는 단어가 있는가? (rationale? escalate? evidence?)
   - 결정 버튼을 찾는 데 어려움이 있는가?
   - 뭘 더 알고 싶다고 하는가?

6. 결정을 완료한 뒤 물어보기:
   - "이 화면 뭐하는 거였어?"
   - "어려운 거 있었어?"
   - "뭐가 부족했어?"

### 기록할 것
- 이해까지 걸린 시간 (체감)
- 헷갈려한 단어나 UI 요소
- "이건 없으면 결정 못 하겠다" 하는 것
- 전체 소감 (한 줄)

---

## 3.1 — 3개월 뒤 감사 시뮬레이션 (10분)

**목적**: ledger에 저장된 데이터만 보고 "왜 이 결정을 내렸는지" 복원 가능한가?

### 방법

1. 터미널 B에서 지금까지 쌓인 ledger 조회:
```bash
curl -s http://localhost:4000/ledger | python3 -m json.tool | head -80
```

2. 아무 entry 하나 골라서 자세히 보기:
```bash
# thread_id로 필터 (아까 실행한 것 중 하나)
curl -s "http://localhost:4000/ledger?thread_id=<아무_thread_id>" | python3 -m json.tool
```

3. 그 entry의 `content` 필드를 읽으면서 자문하기:
   - 누가 결정했는가? (`approval.approver_email`)
   - 언제? (`approval.decided_at`)
   - 뭘 결정했는가? (`approval.decision_type`, `decision_payload`)
   - 왜? (`approval.rationale_category`, `rationale_notes`)
   - 어떤 맥락에서? (`interrupt` → subject, amount, customer, evidence)
   - 이 정보만으로 3개월 뒤 감사관이 "이 결정은 합리적이었다"고 판단할 수 있나?

4. 부족한 게 있으면 기록:
   - 예: "당시 정책이 뭐였는지 모름", "관련 다른 결정 찾기 어려움"

### 기록할 것
- JSON만으로 맥락 복원 가능한가? (예/아니오 + 이유)
- 부족한 필드가 있다면?
- `rationale_notes`가 비어있으면 — 그게 문제인가?

---

## 3.2 — 컴플라이언스 쿼리 (5분)

**목적**: "지난주 $500 이상 환불 모두 보여줘" 같은 감사 요청에 답할 수 있는가?

### 방법
```bash
# 전체 ledger에서 $500 이상 필터
curl -s http://localhost:4000/ledger | python3 -c "
import json, sys
entries = json.load(sys.stdin)
for e in entries:
    amount = e.get('content', {}).get('interrupt', {}).get('amount', {})
    if amount and amount.get('value', 0) >= 500:
        approval = e['content'].get('approval') or {}
        print(f'{e[\"content\"][\"created_at\"]} | {amount[\"value\"]} {amount.get(\"currency\",\"\")} | {approval.get(\"decision_type\", \"pending\")} | {e[\"content\"].get(\"thread_id\",\"\")[:20]}')
"
```

### 기록할 것
- 쿼리 쓰기 쉬웠나?
- 결과에 필요한 정보 다 있나?

---

## 3.3 — Hash 검증 (5분)

**목적**: ledger의 content_hash가 실제로 검증 가능한가?

### 방법
```bash
curl -s http://localhost:4000/ledger | python3 -c "
import hashlib, json, sys
entries = json.load(sys.stdin)
ok = 0
fail = 0
for entry in entries:
    content = dict(entry['content'])
    stored_hash = content.pop('content_hash', '')
    content.pop('signature', None)
    canonical = json.dumps(content, sort_keys=True, separators=(',', ':'), default=str)
    computed = 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()
    if computed == stored_hash:
        ok += 1
    else:
        fail += 1
        print(f'MISMATCH: {entry[\"id\"]}')
print(f'Total: {ok + fail}, OK: {ok}, Failed: {fail}')
"
```

### 기록할 것
- 모두 OK인가?
- 실패한 게 있으면 어떤 entry인가?

---

## 4.1 — 30분~1시간 뒤 승인 (30분+)

**목적**: 에이전트가 오래 대기해도 정상 동작하는가?

### 방법

1. 에이전트 실행:
```bash
uv run python agent.py
```

2. URL 출력되면 **브라우저에서 열지 않기**. 그냥 두기.

3. **30분~1시간 다른 일 하기** (진짜로)

4. 돌아와서:
   - 터미널 A에서 에이전트가 아직 polling 중인가? (로그가 계속 나오고 있으면 OK)
   - 만약 에러로 죽었다면 — 어떤 에러?
   - 아직 살아있으면 브라우저에서 URL 열고 승인하기
   - 에이전트가 재개되는가?

### 기록할 것
- 에이전트가 X분 후에도 살아있었나?
- 승인 후 정상 재개됐나?
- (1시간 이후면 timeout 에러가 날 수 있음 — 그것도 기록)

---

## 4.3 — 네트워크 끊김 (5분)

**목적**: Submit 순간 네트워크가 끊기면 어떻게 되는가?

### 방법

1. 에이전트 실행, URL 열기, 결정 선택까지 하기 (Submit은 아직 안 누름)

2. **WiFi 끄기** (맥 메뉴바에서 WiFi off)

3. Submit Decision 누르기

4. 관찰:
   - 에러 메시지가 나오는가?
   - 입력한 rationale/notes가 사라지는가?
   - 화면이 멈추는가?

5. **WiFi 다시 켜기**

6. 다시 Submit 시도:
   - 재시도 가능한가?
   - 이전 입력이 유지되는가?

### 기록할 것
- 에러 메시지가 사용자 친화적인가?
- 입력 데이터가 보존되는가?
- WiFi 복원 후 재시도 동작하는가?

---

## 4.4 — 서버 재시작 (5분)

**목적**: 서버가 재시작되면 에이전트와 UI가 복구되는가?

### 방법

1. 에이전트 실행 (polling 상태)
2. 브라우저에서 URL 열어두기 (submit은 안 함)

3. 터미널 B에서:
```bash
docker compose restart server
```

4. 10초 대기

5. 관찰:
   - 에이전트: polling이 에러 뿜는가? 복구되는가?
   - 브라우저: 새로고침하면 페이지 로드되는가?
   - Submit하면 동작하는가?

### 기록할 것
- 에이전트가 자동 복구됐나?
- 몇 초간 에러가 났나?
- UI는 새로고침 후 정상인가?

---

## 5 — Dogfooding (며칠, 시간 될 때)

**목적**: refund agent가 아닌 **당신의 실제 워크플로우**에 Deliberate를 붙여보기.
LangGraph를 몰라도 됩니다. 아래에 복사-붙여넣기로 만들 수 있는 완전한 예제가 있습니다.

### 아이디어
- 채널톡 자동 응답 → 전송 전 검토
- Enkostay 게스트 문의 자동 답변 → 전송 전 확인
- 블로그 글 AI 생성 → 발행 전 검토
- 이메일 초안 → 전송 전 approve

### 설치 (한 번만)

```bash
cd examples/refund_agent
# 이미 venv이 있으면 스킵
uv venv && uv pip install -e ../../sdk "langgraph>=0.3,<0.5"
```

### 예제: CS 응답 검토 에이전트

아래 파일을 `examples/refund_agent/dogfood.py`로 저장하세요.
LangGraph의 핵심 구조는 3가지뿐입니다:
- **State**: 데이터를 담는 딕셔너리 (TypedDict)
- **Node**: State를 받아서 수정하는 함수
- **Graph**: 노드를 연결해서 실행 순서를 정하는 것

```python
"""Dogfooding 에이전트 — CS 응답 검토.

사용법:
    export DELIBERATE_SERVER_URL=http://localhost:4000
    export DELIBERATE_API_KEY=SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs
    export DELIBERATE_UI_URL=http://localhost:3000
    uv run python dogfood.py
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from deliberate import approval_gate


# ================================================================
# 1단계: State 정의 — 에이전트가 다루는 데이터 구조
# ================================================================

class ReviewState(TypedDict):
    # 입력
    customer_name: str
    original_question: str
    # AI가 생성한 응답 초안
    draft_response: str
    # 승인 결과 (Deliberate가 채워줌)
    decision: dict[str, Any] | None


# ================================================================
# 2단계: 노드(함수) 정의 — 각각이 하나의 "작업 단계"
# ================================================================

def generate_response(state: ReviewState) -> dict[str, Any]:
    """AI가 CS 응답을 생성하는 단계.
    
    실제로는 여기서 OpenAI/Claude API를 호출하겠지만,
    dogfooding에서는 하드코딩된 응답을 사용합니다.
    """
    # TODO: 실제 use case에서는 LLM 호출
    draft = (
        f"안녕하세요 {state['customer_name']}님,\n\n"
        f"문의하신 내용 확인했습니다: \"{state['original_question']}\"\n\n"
        f"확인 결과, 해당 건은 처리 가능합니다. "
        f"추가 문의사항이 있으시면 말씀해주세요.\n\n"
        f"감사합니다."
    )
    print(f"[AI] 응답 초안 생성 완료 ({len(draft)}자)")
    return {"draft_response": draft}


@approval_gate(layout="financial_decision")
def review_response(state: ReviewState) -> dict[str, Any]:
    """사람이 검토하는 단계.
    
    이 함수가 반환하는 dict가 승인 페이지에 표시됩니다.
    @approval_gate가 나머지를 처리: 서버 전송 → 대기 → 결과 반환.
    """
    return {
        "subject": f"CS 응답 검토: {state['customer_name']}",
        # amount는 없어도 됨 (financial_decision 레이아웃에서 선택사항)
        "customer": {
            "id": state["customer_name"],
            "display_name": state["customer_name"],
        },
        # agent_reasoning에 초안 응답을 넣으면 검토자가 볼 수 있음
        "agent_reasoning": state["draft_response"],
        # evidence에 원본 문의를 넣음
        "evidence": [
            {
                "type": "customer_inquiry",
                "id": None,
                "summary": state["original_question"],
                "url": None,
            },
        ],
        # 이 use case에 맞는 rationale 카테고리
        "rationale_categories": [
            "appropriate",      # 적절한 응답
            "needs_revision",   # 수정 필요
            "wrong_tone",       # 톤 부적절
            "factual_error",    # 사실 오류
        ],
    }


def send_response(state: ReviewState) -> dict[str, Any]:
    """승인된 응답을 전송하는 단계."""
    decision = state.get("decision")
    if not decision:
        print("[!] 결정 없음 — 전송 스킵")
        return {}

    decision_type = decision.get("decision_type", "unknown")

    if decision_type == "approve":
        print(f"\n{'='*50}")
        print(f"응답 전송 완료!")
        print(f"  고객: {state['customer_name']}")
        print(f"  응답: {state['draft_response'][:80]}...")
        print(f"  판정: {decision_type}")
        print(f"  사유: {decision.get('rationale_category', 'N/A')}")
        print(f"{'='*50}\n")
    elif decision_type == "reject":
        print(f"\n[X] 응답 거부됨 — 전송하지 않음")
        print(f"    사유: {decision.get('rationale_notes', 'N/A')}")
    else:
        print(f"\n[?] 판정: {decision_type}")
        print(f"    사유: {decision.get('rationale_notes', 'N/A')}")

    return {}


# ================================================================
# 3단계: 그래프 구성 — 노드를 연결
# ================================================================

def should_send(state: ReviewState) -> str:
    """승인됐으면 전송, 아니면 종료."""
    if state.get("decision"):
        return "send_response"
    return END


def build_graph() -> StateGraph:
    graph = StateGraph(ReviewState)

    # 노드 등록
    graph.add_node("generate_response", generate_response)
    graph.add_node("review_response", review_response)
    graph.add_node("send_response", send_response)

    # 실행 순서: generate → review → (조건) → send 또는 END
    graph.set_entry_point("generate_response")
    graph.add_edge("generate_response", "review_response")
    graph.add_conditional_edges("review_response", should_send)
    graph.add_edge("send_response", END)

    return graph


# ================================================================
# 4단계: 실행
# ================================================================

def main() -> None:
    print("\n" + "="*50)
    print("Dogfooding — CS 응답 검토 에이전트")
    print("="*50 + "\n")

    graph = build_graph()
    app = graph.compile()

    # -------------------------------------------------------
    # 여기를 바꿔서 실제 use case 테스트!
    # -------------------------------------------------------
    initial_state: ReviewState = {
        "customer_name": "김민지",
        "original_question": "예약한 숙소 체크인 시간을 변경할 수 있나요?",
        "draft_response": "",  # generate_response가 채울 것
        "decision": None,
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"고객: {initial_state['customer_name']}")
    print(f"문의: {initial_state['original_question']}")
    print(f"Thread: {thread_id}\n")

    result = app.invoke(initial_state, config=config)

    print("\n에이전트 완료.")
    if result.get("decision"):
        print(f"최종 판정: {result['decision'].get('decision_type', 'unknown')}")


if __name__ == "__main__":
    main()
```

### 실행 방법

```bash
cd examples/refund_agent

# 환경변수 (매번 필요)
export DELIBERATE_SERVER_URL=http://localhost:4000
export DELIBERATE_API_KEY=SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs
export DELIBERATE_UI_URL=http://localhost:3000

# 실행
uv run python dogfood.py
```

출력:
```
Dogfooding — CS 응답 검토 에이전트
고객: 김민지
문의: 예약한 숙소 체크인 시간을 변경할 수 있나요?

[AI] 응답 초안 생성 완료 (142자)

[DELIBERATE] Approval needed: http://localhost:3000/a/xxxxx
```

→ URL을 브라우저에서 열면 승인 페이지가 나옴
→ AI 초안 응답이 "Agent Reasoning" 영역에 표시됨
→ 원본 문의가 "Evidence" 테이블에 표시됨
→ Approve/Reject 결정

### 커스터마이징 포인트

코드에서 바꿀 수 있는 부분:

| 바꿀 것 | 위치 | 예시 |
|---------|------|------|
| 고객명/문의 내용 | `main()` 안의 `initial_state` | 실제 CS 문의로 교체 |
| AI 응답 생성 | `generate_response()` | OpenAI API 호출로 교체 |
| 승인 페이지에 표시할 정보 | `review_response()` 안의 return dict | 필드 추가/변경 |
| 판정 카테고리 | `rationale_categories` 리스트 | 도메인에 맞게 변경 |
| 승인 후 동작 | `send_response()` | 실제 메시지 전송 API 호출 |

### 5~10회 실사용 시나리오

매번 `initial_state`의 문의 내용을 바꿔서 실행:

```python
# 시나리오 1
"original_question": "예약한 숙소 체크인 시간을 변경할 수 있나요?",

# 시나리오 2
"original_question": "환불 규정이 어떻게 되나요? 내일 체크인인데 취소하고 싶어요",

# 시나리오 3
"original_question": "숙소에 주차장이 있나요? 반려동물 동반도 가능한가요?",

# 시나리오 4
"original_question": "에어컨이 안 돼요. 지금 너무 더운데 어떻게 해야 하나요?",

# 시나리오 5
"original_question": "조식 포함인가요? 근처에 맛집 추천해주세요",
```

### 기록할 것

각 시나리오마다:

1. **레이아웃 적합성**: `financial_decision` 레이아웃이 CS 응답 검토에 맞는가?
   - "Amount" 카드가 나오는가? (없으면 안 나옴 — OK)
   - "Agent Reasoning"에 AI 초안이 잘 보이는가?
   - 빠져있는 정보가 있는가? (예: 응답 수정 기능, 원본 대화 맥락)

2. **카테고리 적합성**: `appropriate`, `needs_revision`, `wrong_tone`, `factual_error`가 실제 판단에 맞는가?
   - 없는 카테고리가 필요한가?
   - 너무 많은가?

3. **실용성 판단** (가장 중요):
   - "이 워크플로우를 실제로 매일 쓸 것 같은가?"
   - "Slack에서 바로 확인하는 게 나을까, 이 UI가 나을까?"
   - "이 검토 과정이 응답 품질을 실제로 올릴까?"

---

## 우선순위 — 시간 없으면 이것만

**1시간**: 2.1 (15분) → 2.4 (15분) → 3.1 (10분) → CLAUDE.md 업데이트 (15분)

**2시간**: 위 + 2.3 (15분) + 4.1 (30분) + 3.2/3.3 (10분)

**절대 스킵하지 말 것**: 2.1 (30초 룰)과 2.4 (비엔지니어). 핵심 가치 제안 검증.

---

## 결과 기록 후

모든 테스트 끝나면 결과를 Claude Code에 알려주세요. `CLAUDE.md`와 `docs/M1_MANUAL_TEST_LOG.md`에 정리해드립니다.

### 발견 분류 기준

- **P0**: M2 시작 전 반드시 해결 (UX 핵심 약속 깨짐)
- **P1**: M2 범위 내 해결 (알려진 제한사항, M2가 다룸)
- **P2**: 백로그 (중요하지만 급하지 않음)
- **Schema gap**: PRD 자체 문제 → PRD v3 업데이트
