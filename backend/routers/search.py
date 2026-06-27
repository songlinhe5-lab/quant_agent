from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.search_service import search_service

router = APIRouter(prefix="/search", tags=["Search"])

class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None

@router.post("/web")
async def web_search(req: WebSearchRequest):
    """后端提供给 Agent 调用的统一网络搜索入口"""
    try:
        return await search_service.web_search(
            query=req.query, max_results=req.max_results, 
            include_domains=req.include_domains, exclude_domains=req.exclude_domains
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))