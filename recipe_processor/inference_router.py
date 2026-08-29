"""
Layer 3: Groq LPU Inference Router & Multi-Model Execution Engine.
Routes requests across Groq LPU models (llama-3.3-70b-versatile, llama-3.1-8b-instant)
with deterministic Temperature = 0.0 and fallbacks to Google Gemini, OpenAI, and Ollama.
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
import logging
from typing import Optional, Dict, Any

from .prompt_orchestrator import PromptOrchestrator

logger = logging.getLogger(__name__)


class InferenceRouter:
    """
    Manages deterministic structured inference across Groq LPUs and fallback LLMs.
    """

    @classmethod
    def extract_recipe_json(cls, text: str) -> Optional[Dict[str, Any]]:
        """
        Main routing function: tries Groq LPU -> Gemini -> OpenAI -> Ollama.
        Returns parsed JSON dict or None if all backends fail.
        """
        system_prompt = PromptOrchestrator.get_system_prompt()
        user_prompt = PromptOrchestrator.format_user_prompt(text)
        word_count = len(text.split())

        # Determine optimal Groq model: 8b fast-path for short text, 70b versatile for complex
        groq_api_key = os.environ.get("GROQ_API_KEY")
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        openai_api_key = os.environ.get("OPENAI_API_KEY")

        raw_json_str = None

        # 1. Primary: Groq LPU Inference Engine
        if groq_api_key:
            groq_models = (
                ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
                if word_count < 300
                else ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b"]
            )
            raw_json_str = cls._call_groq(groq_api_key, groq_models, system_prompt, user_prompt)

        # 2. Fallback: Google Gemini API (2.0 Flash)
        if not raw_json_str and gemini_api_key:
            raw_json_str = cls._call_gemini(gemini_api_key, system_prompt, user_prompt)

        # 3. Fallback: OpenAI API (gpt-4o-mini)
        if not raw_json_str and openai_api_key:
            raw_json_str = cls._call_openai(openai_api_key, system_prompt, user_prompt)

        # 4. Fallback: Local Ollama
        if not raw_json_str:
            raw_json_str = cls._call_ollama(system_prompt, user_prompt)

        if not raw_json_str:
            return None

        # Clean markdown code blocks if returned
        match = re.search(r"(\{.*\})", raw_json_str, re.DOTALL)
        if match:
            raw_json_str = match.group(1)

        try:
            return json.loads(raw_json_str)
        except Exception as exc:
            logger.warning("Failed to parse LLM response as JSON: %s (Raw: %s)", exc, raw_json_str[:200])
            return None

    @classmethod
    def _call_groq(cls, api_key: str, models: list, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Execute request against Groq LPU API with temperature=0.0."""
        for model in models:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "Grams/2.0"
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "").strip()
                    if content:
                        logger.info("Groq LPU [%s] extracted recipe successfully.", model)
                        return content
            except urllib.error.HTTPError as err:
                if err.code == 429:
                    logger.warning("Groq rate limit on %s, trying next model...", model)
                else:
                    logger.warning("Groq model %s error %d: %s", model, err.code, err.reason)
            except Exception as e:
                logger.warning("Groq model %s failed: %s", model, e)

        return None

    @classmethod
    def _call_gemini(cls, api_key: str, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Execute request against Google Gemini API with response_mime_type=application/json."""
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        for model in ("gemini-2.0-flash", "gemini-1.5-flash"):
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": combined_prompt}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0}
            }).encode("utf-8")

            req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        logger.info("Gemini [%s] extracted recipe successfully.", model)
                        return parts[0].get("text", "").strip()
            except Exception as e:
                logger.warning("Gemini model %s failed: %s", model, e)

        return None

    @classmethod
    def _call_openai(cls, api_key: str, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Execute request against OpenAI API with json_object mode."""
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                logger.info("OpenAI gpt-4o-mini extracted recipe successfully.")
                return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning("OpenAI API failed: %s", e)

        return None

    @classmethod
    def _call_ollama(cls, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Execute request against local Ollama instance."""
        try:
            import config
            base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
            model = getattr(config, "OLLAMA_MODEL", "llama3.1")

            payload = json.dumps({
                "model": model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "options": {"temperature": 0.0},
                "format": "json"
            }).encode("utf-8")

            endpoint = f"{base_url.rstrip('/')}/api/generate"
            req = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")

            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            res = data.get("response", "").strip()
            if res:
                logger.info("Local Ollama extracted recipe successfully.")
                return res
        except Exception as e:
            logger.debug("Ollama unavailable: %s", e)

        return None
