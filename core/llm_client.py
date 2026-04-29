"""
LlmClient — handles LLM API calls with retry and fallback.
LlmClient — 处理LLM API调用，支持重试和降级。

This module provides:
本模块提供：
- chat(): main entry point, tries primary endpoint then fallback
  chat(): 主入口，先尝试主端点，失败后降级到备用端点
- parse_json_array(): extract JSON array from LLM response (handles markdown fences)
  parse_json_array(): 从 LLM 响应中提取 JSON 数组（处理markdown代码块）
- Supports both OpenAI and Azure APIM auth headers
  同时支持 OpenAI 和 Azure APIM 认证头
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from core.models import AppConfig
from core.utils import log_event, request_with_retry


class LlmClient:
    """Communicates with OpenAI-compatible LLM endpoints (primary + fallback).
    与OpenAI兼容的LLM端点通信（主端点 + 备用端点）。
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    # ── public API | 公开接口 ───────────────────────────────────────────
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 2,
        delay_seconds: float = 5.0,
    ) -> str:
        """Send a chat completion request; fallback to secondary endpoint on failure.
        发送聊天补全请求；主端点失败时降级到备用端点。
        Returns the LLM response content string. | 返回LLM响应内容字符串。
        """
        try:
            return self._call(
                endpoint=self.config.llm_endpoint,
                api_key=self.config.llm_api_key,
                model=self.config.llm_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                retries=retries,
                delay_seconds=delay_seconds,
                label="primary",
            )
        except Exception as primary_err:
            fb_endpoint = getattr(self.config, "llm_fallback_endpoint", "")
            fb_key = getattr(self.config, "llm_fallback_api_key", "")
            fb_model = getattr(self.config, "llm_fallback_model", "")
            if fb_endpoint and fb_key and fb_model:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "llm_primary_failed_using_fallback",
                    primary_model=self.config.llm_model,
                    fallback_model=fb_model,
                    error=str(primary_err),
                )
                return self._call(
                    endpoint=fb_endpoint,
                    api_key=fb_key,
                    model=fb_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    retries=retries,
                    delay_seconds=delay_seconds,
                    label="fallback",
                )
            raise

    @staticmethod
    def parse_json_array(content: str) -> list[Any]:
        """Extract a JSON array from LLM response text, stripping markdown fences.
        从LLM响应文本中提取JSON数组，去除markdown代码块标记。
        """
        value = (content or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", value)
            value = re.sub(r"\n```$", "", value).strip()
        start = value.find("[")
        end = value.rfind("]")
        if start == -1 or end == -1 or end < start:
            raise ValueError("LLM response did not contain a JSON array")
        return json.loads(value[start : end + 1])

    @staticmethod
    def parse_json_value(content: str) -> Any:
        """Extract a JSON value (object or array) from LLM response.
        从 LLM 响应中提取 JSON 值（对象或数组）。

        Supports v8 (object with headline/tldr/stories) and v5 (array) shapes.
        同时支持 v8（对象）与 v5（数组）两种形式。
        """
        value = (content or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", value)
            value = re.sub(r"\n```$", "", value).strip()
        obj_start = value.find("{")
        arr_start = value.find("[")
        if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
            end = value.rfind("}")
            if end == -1 or end < obj_start:
                raise ValueError("LLM response did not contain a JSON object")
            return json.loads(value[obj_start : end + 1])
        if arr_start != -1:
            end = value.rfind("]")
            if end == -1 or end < arr_start:
                raise ValueError("LLM response did not contain a JSON array")
            return json.loads(value[arr_start : end + 1])
        raise ValueError("LLM response did not contain a JSON object or array")

    # ── internal helpers | 内部工具方法 ─────────────────────────────────────
    def _call(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        retries: int,
        delay_seconds: float,
        label: str,
    ) -> str:
        """Low-level LLM HTTP call with retry logic.
        底层LLM HTTP调用，包含重试逻辑。
        Sends both Bearer and Ocp-Apim-Subscription-Key headers for Azure compat.
        同时发送 Bearer 和 Ocp-Apim-Subscription-Key 头以兼容 Azure。
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.llm_temperature,
            "max_completion_tokens": self.config.llm_max_tokens,
        }
        session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer %s" % api_key
            headers["Ocp-Apim-Subscription-Key"] = api_key
        try:
            for attempt in range(1, retries + 2):
                try:
                    response = request_with_retry(
                        session=session,
                        method="POST",
                        url=endpoint,
                        timeout=self.config.llm_timeout,
                        logger=self.logger,
                        retries=0,
                        delay=0,
                        json=payload,
                        headers=headers,
                    )
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("LLM response content was empty")
                    log_event(
                        self.logger,
                        logging.INFO,
                        "llm_call_succeeded",
                        label=label,
                        model=model,
                        attempt=attempt,
                    )
                    return content
                except Exception as exc:
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "llm_call_failed",
                        label=label,
                        model=model,
                        attempt=attempt,
                        error=str(exc),
                    )
                    if attempt <= retries:
                        time.sleep(delay_seconds)
                    else:
                        raise
        finally:
            session.close()
        raise RuntimeError("LLM call exited without a response")
