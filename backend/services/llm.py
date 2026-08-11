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
            "max_tokens": 400,
            "response_format": {"type": "json_object"}
        }
        
        url = f"{settings.llm_api_url.rstrip('/')}/chat/completions"
        logger.debug(f"Calling LLM API: {url} with model {payload['model']}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"].strip()
                return content
            return None
    except Exception as e:
        logger.error(f"LLM API call failed: {e.__class__.__name__} {e}")
        return None

async def generate_search_variants_with_llm(
    target_title: str, 
    target_year: Optional[int] = None, 
    season: Optional[int] = None,
    episode: Optional[int] = None,
    air_date: Optional[str] = None
) -> List[str]:
    """
    Asks the LLM to generate a JSON list of probable naming formats/search variants for a movie or TV episode 
    that Indian torrent sites might use.
    """
    try:
        from sqlmodel import Session
        from backend.database import engine
        
        with Session(engine) as session:
            settings = get_settings(session)
            
        if not settings.llm_enabled:
            return []

        prompt = (
            f"Generate 5 highly probable exact string formats that Indian torrent/streaming sites (like 1TamilMV, BollyZone) "
            f"might use to name the following media release.\n"
            f"Target Media: {target_title} ({target_year or 'Unknown Year'})\n"
        )
        if season is not None and episode is not None:
            prompt += f"Season: {season}, Episode: {episode}\n"
        elif episode is not None:
            prompt += f"Episode: {episode}\n"
        elif air_date is not None:
            prompt += f"Air Date: {air_date}\n"
            
        system_prompt = (
            "You are a strict JSON data generator. "
            "Your entire response MUST be ONLY a valid JSON object containing a 'variants' key with a list of strings. "
            "Do NOT output any conversational text, greetings, reasoning, or markdown blocks. Just the raw JSON object.\n"
            "Example format: {\"variants\": [\"Show Season 1 Episode 2\", \"Show 1 Episode 2\", \"Show S01 E02\", \"Show S1E2\"]}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        result = await _call_llm_api(messages, settings)
        if not result:
            return []
            
        import json
        
        # Try to find JSON array or object
        try:
            # Clean markdown code blocks just in case
            import re
            cleaned = re.sub(r'```(?:json)?\s*', '', result).strip()
            
            start = -1
            for i, c in enumerate(cleaned):
                if c in '{[':
                    start = i
                    break
                    
            if start != -1:
                end = -1
                for i in range(len(cleaned)-1, -1, -1):
                    if cleaned[i] in '}]':
                        end = i
                        break
                        
                if end > start:
                    json_str = cleaned[start:end+1]
                    data = json.loads(json_str)
                    
                    if isinstance(data, dict) and "variants" in data and isinstance(data["variants"], list):
                        return [str(v).lower() for v in data["variants"]]
                    elif isinstance(data, list):
                        return [str(v).lower() for v in data]
        except Exception:
            pass
                
        # Fallback if structured parsing failed
        logger.warning(f"LLM failed to return valid JSON for search variants. Raw: {result}")
        import re
        matches = re.findall(r'"([^"]+)"', result)
        if matches:
            # Filter out the key name itself and any long conversational strings
            return [m.lower() for m in matches if len(m) < 100 and m.lower() != "variants"]
            
        return []

    except Exception as e:
        logger.error(f"LLM variant generation failed: {e}")
        return []
