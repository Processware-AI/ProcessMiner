"""Claude 호출을 한곳으로 모은다.

파이프라인은 여기의 structured() 만 쓴다. 모델·사고 깊이·거절 처리 같은 호출 방식이
한곳에 있어야, 어떤 모델이 어떤 결과를 만들었는지 일관되게 기록할 수 있다.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import anthropic
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

# 모델이 안전 정책으로 응답을 거절했을 때, 같은 요청을 다른 모델로 이어서 처리하게 한다.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """모델 호출이 쓸 수 있는 결과를 내지 못했다. 메시지는 화면에 보여줄 수 있는 문장이다."""


@dataclass
class LLMResult[T: BaseModel]:
    output: T
    model: str  # 실제로 응답한 모델
    input_tokens: int
    output_tokens: int


@lru_cache
def get_client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    # 키를 지정하지 않으면 SDK 가 환경 변수나 로그인 프로필에서 인증 정보를 찾는다.
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def structured[T: BaseModel](
    *,
    system: str,
    user: str,
    schema: type[T],
    max_tokens: int = 32000,
    effort: str | None = None,
) -> LLMResult[T]:
    """한 번 묻고, schema 에 맞는 답을 받는다."""
    settings = get_settings()
    try:
        # 출력이 길 수 있어 스트리밍으로 받는다(긴 요청의 시간 초과 방지).
        with get_client().beta.messages.stream(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort or settings.llm_effort},
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise LLMError("API 키가 올바르지 않습니다. 설정을 확인하세요.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMError("이 API 키로는 해당 모델을 쓸 수 없습니다.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("호출 한도를 넘었습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIStatusError as exc:
        logger.error(
            "LLM 호출 실패 %s: %s (request %s)", exc.status_code, exc.message, exc.request_id
        )
        raise LLMError(f"모델 호출이 실패했습니다({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("모델 서버에 연결하지 못했습니다.") from exc

    if message.stop_reason == "refusal":
        raise LLMError("모델이 이 내용의 처리를 거절했습니다.")
    if message.stop_reason == "max_tokens":
        raise LLMError("응답이 너무 길어 중간에 끊겼습니다. 더 작은 단위로 나눠 처리해야 합니다.")
    if message.parsed_output is None:
        raise LLMError("모델 응답을 정해진 형식으로 읽지 못했습니다.")

    return LLMResult(
        output=message.parsed_output,
        model=message.model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
