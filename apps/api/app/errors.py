from fastapi import HTTPException


def api_error(status: int, code: str, message: str, **extra) -> HTTPException:
    """화면에 그대로 보여줄 수 있는 메시지와 분기용 코드를 함께 담는다."""
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _object_particle(word: str) -> str:
    """목적격 조사. 마지막 글자에 받침이 있으면 '을', 없으면 '를'."""
    last = word[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - ord("가")) % 28 else "를"
    return "을(를)"


def not_found(what: str = "대상") -> HTTPException:
    return api_error(404, "not_found", f"{what}{_object_particle(what)} 찾을 수 없습니다.")


def forbidden(message: str = "이 작업을 수행할 권한이 없습니다.") -> HTTPException:
    return api_error(403, "forbidden", message)
