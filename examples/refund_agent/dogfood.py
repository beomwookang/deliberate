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
