"""
Web 页面路由
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return request.app.state.templates.TemplateResponse(  # type: ignore[attr-defined]
        "dashboard.html",
        {"request": request},
    )

