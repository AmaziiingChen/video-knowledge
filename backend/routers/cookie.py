from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel
from config import settings
from services.bilibili_auth import clear_saved_bilibili_cookie, get_bilibili_cookie_status, save_bilibili_cookie
from services.cookie_files import write_cookie_pairs_to_netscape
from services.douyin_cookie_status import get_douyin_cookie_status, invalidate_douyin_cookie_status
from services.xiaohongshu_client import clear_xiaohongshu_cookie, save_xiaohongshu_cookie, xiaohongshu_cookie_status

router = APIRouter()

class CookieRequest(BaseModel):
    cookie: str

class CookieResponse(BaseModel):
    success: bool
    message: str

@router.get("/cookie", response_model=dict)
def get_cookie_status(
    refresh: bool = Query(default=False),
    probe: bool = Query(default=True),
):
    return get_douyin_cookie_status(force=refresh, probe=probe)

@router.post("/cookie", response_model=CookieResponse)
async def set_cookie(req: CookieRequest):
    cookie_str = req.cookie.strip()
    if not cookie_str:
        return CookieResponse(success=False, message="Cookie 不能为空")
    
    try:
        cookie_file = settings.data_dir / "douyin_cookies.txt"
        _write_netscape_cookie_file(cookie_str, cookie_file)
        
        invalidate_douyin_cookie_status()
        return CookieResponse(success=True, message="Cookie 已保存")
    except Exception as e:
        return CookieResponse(success=False, message=f"保存失败: {str(e)}")


@router.delete("/cookie", response_model=CookieResponse)
def clear_cookie():
    try:
        cookie_file = settings.data_dir / "douyin_cookies.txt"
        cookie_file.unlink(missing_ok=True)
        invalidate_douyin_cookie_status()
        return CookieResponse(success=True, message="抖音登录凭据已断开")
    except OSError as exc:
        return CookieResponse(success=False, message=f"断开失败: {exc}")

@router.get("/bilibili-cookie", response_model=dict)
def get_bilibili_cookie():
    return get_bilibili_cookie_status()


@router.post("/bilibili-cookie", response_model=CookieResponse)
def set_bilibili_cookie(req: CookieRequest):
    cookie_str = req.cookie.strip()
    if not cookie_str:
        return CookieResponse(success=False, message="B站 Cookie 不能为空")
    try:
        save_bilibili_cookie(cookie_str)
        return CookieResponse(success=True, message="B站 Cookie 已保存")
    except (OSError, ValueError) as exc:
        return CookieResponse(success=False, message=f"保存失败: {exc}")


@router.delete("/bilibili-cookie", response_model=CookieResponse)
def clear_bilibili_cookie():
    try:
        clear_saved_bilibili_cookie()
        return CookieResponse(success=True, message="B站登录凭据已断开")
    except OSError as exc:
        return CookieResponse(success=False, message=f"断开失败: {exc}")


@router.get("/xiaohongshu-cookie", response_model=dict)
def get_xiaohongshu_cookie(refresh: bool = Query(default=False)):
    return xiaohongshu_cookie_status(probe=refresh)


@router.post("/xiaohongshu-cookie", response_model=CookieResponse)
def set_xiaohongshu_cookie(req: CookieRequest):
    try:
        save_xiaohongshu_cookie(req.cookie)
        return CookieResponse(success=True, message="小红书 Cookie 已保存")
    except (OSError, ValueError) as exc:
        return CookieResponse(success=False, message=f"保存失败: {exc}")


@router.delete("/xiaohongshu-cookie", response_model=CookieResponse)
def clear_xiaohongshu_cookie_endpoint():
    try:
        clear_xiaohongshu_cookie()
        return CookieResponse(success=True, message="小红书登录凭据已断开")
    except OSError as exc:
        return CookieResponse(success=False, message=f"断开失败: {exc}")


def _write_netscape_cookie_file(cookie_str: str, output_path: Path):
    return write_cookie_pairs_to_netscape(cookie_str, output_path, ".douyin.com")
