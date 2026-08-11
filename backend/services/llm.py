import httpx
import logging
import json
from typing import Optional, List, Tuple
from backend.database import get_session, get_settings
from backend.models import AppSettings

logger = logging.getLogger(__name__)

async def _call_llm_api(messages: list, settings: AppSettings) -> Optional[str]:
    """Internal helper to make the API call to the configured LLM endpoint."""
    if not settings.llm_enabled or not settings.llm_api_url:
        return None

    try:
        headers = {
            "Content-Type": "application/json"
        }
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        payload = {
            "model": settings.llm_model or "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 150
        }
        
        url = f"{settings.llm_api_url.rstrip('/')}/chat/completions"
        logger.debug(f"Calling LLM API: {url} with model {payload['model']}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"].strip()
                return content
            return None
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return None

async def parse_tracker_results_with_llm(
    links: List[Tuple[str, str]], 
    target_title: str, 
    target_year: Optional[int] = None, 
    target_resolution: Optional[str] = None
) -> Optional[str]:
    """
    Passes a list of (url, text) tuples to the LLM to intelligently pick the best matching URL.
    Returns the URL if found, else None.
    """
    try:
        # We need settings inside this async function context
        # Since this is a service, we'll manually fetch a session
        from sqlmodel import Session
        from backend.database import engine
        
        with Session(engine) as session:
            settings = get_settings(session)
            
        if not settings.llm_enabled:
            return None

        # Format the links for the LLM
        formatted_links = "\n".join([f"- URL: {href}\n  Title: {text}" for href, text in links])
        
        prompt = (
            f"Target Media: {target_title} ({target_year or 'Unknown Year'})\n"
        )
        if target_resolution:
            prompt += f"Preferred Resolution: {target_resolution}\n"
            
        prompt += (
            f"\nAvailable Results:\n{formatted_links}"
        )
        
        system_prompt = (
            "You are a strict, intelligent movie/TV parser. Your job is to select the exact URL of the best matching release from the provided list.\n"
            "Rules:\n"
            "1. Exclude any CAM, HDTS, PRE-DVD, or strictly low-quality theatrical recordings.\n"
            "2. If multiple valid options exist, pick the highest quality one that matches the requested resolution/episode.\n"
            "3. If no links seem like a good, genuine match, reply ONLY with the word NONE.\n"
            "4. Your entire response must be ONLY the exact URL (or NONE). Do not include any explanations, reasoning, formatting, or extra text."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        result = await _call_llm_api(messages, settings)
        if not result or "NONE" in result.upper():
            return None
            
        import re
        url_match = re.search(r'(https?://[^\s\'"]+)', result)
        if url_match:
            extracted_url = url_match.group(1)
            for href, _ in links:
                if href in extracted_url or extracted_url in href:
                    return href
                
        logger.warning(f"LLM returned an invalid URL or formatted it weirdly: {result}")
        return None

    except Exception as e:
        logger.error(f"LLM parsing service failed: {e}")
        return None
