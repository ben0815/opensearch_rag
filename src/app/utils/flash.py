from fastapi import Request, Response

_VALID_FLASH_CATEGORIES = {"success", "danger", "warning", "info"}


def set_flash(response: Response, message: str, category: str = "success") -> None:
    response.set_cookie("flash_msg", message, max_age=30, httponly=True, samesite="strict")
    response.set_cookie("flash_cat", category, max_age=30, httponly=True, samesite="strict")


def read_flash(request: Request) -> dict | None:
    """Read flash data from request cookies (non-destructive). Use with clear_flash()."""
    msg = request.cookies.get("flash_msg")
    if not msg:
        return None
    cat = request.cookies.get("flash_cat", "success")
    if cat not in _VALID_FLASH_CATEGORIES:
        cat = "success"
    return {"message": msg, "category": cat}


def clear_flash(response: Response) -> None:
    """Add delete-cookie headers to response. Call after creating TemplateResponse."""
    response.delete_cookie("flash_msg")
    response.delete_cookie("flash_cat")
