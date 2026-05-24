from urllib.parse import quote_plus
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

templates = Jinja2Templates(directory="src/templates")
templates.env.filters["url_encode"] = lambda s: quote_plus(str(s))


def _csrf_input(request) -> Markup:
    token = getattr(getattr(request, "state", None), "csrf_token", "")
    return Markup(f'<input type="hidden" name="csrf_token" value="{escape(token)}">')


templates.env.globals["csrf_input"] = _csrf_input
