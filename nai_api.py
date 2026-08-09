"""NovelAI 图像生成客户端。

走 OpenAI 兼容的 /v1/images/generations 端点，请求体额外携带
negative_prompt 字段（NAI 特有，标准 DALL-E 接口不支持）。
"""

import base64
import binascii
import math
import time

import requests


class NaiAPIError(Exception):
    """生成失败，消息面向用户可读。"""


# 上游偶发 502/503，属于服务端抖动，重试即可恢复
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class NaiAPI:
    def __init__(self, api_base, api_key, model, timeout=180, retry_backoff=1.0):
        self._base = str(api_base or "").rstrip("/")
        self._key = str(api_key or "").strip()
        self._model = str(model or "nai-diffusion-4-5-full").strip()
        try:
            self._timeout = max(1, int(timeout))
        except (TypeError, ValueError):
            self._timeout = 180
        try:
            retry_backoff = float(retry_backoff)
            if not math.isfinite(retry_backoff):
                raise ValueError
            self._retry_backoff = min(8.0, max(0.0, retry_backoff))
        except (TypeError, ValueError):
            self._retry_backoff = 1.0

    @property
    def configured(self):
        return bool(self._base and self._key)

    def generate(self, prompt, negative_prompt, size, retries=3):
        """生成单张图片，返回 PNG 字节。

        对可重试状态码做退避重试；其余错误立即抛出，避免无谓等待。
        """
        if not self.configured:
            raise NaiAPIError("插件未配置 API 地址或密钥，请在管理面板填写。")

        url = f"{self._base}/v1/images/generations"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

        try:
            attempts = max(1, min(5, int(retries)))
        except (TypeError, ValueError):
            attempts = 3

        last_error = "未知错误"
        for attempt in range(attempts):
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=self._timeout
                )
            except requests.Timeout:
                last_error = f"请求超时（{self._timeout} 秒）"
                self._wait_before_retry(attempt, attempts)
                continue
            except requests.RequestException as exc:
                last_error = f"网络异常：{type(exc).__name__}"
                self._wait_before_retry(attempt, attempts)
                continue

            if 200 <= response.status_code < 300:
                return self._extract_image(response)

            if response.status_code in RETRYABLE_STATUS:
                last_error = f"上游返回 {response.status_code}，服务可能不稳定"
                self._wait_before_retry(
                    attempt,
                    attempts,
                    retry_after=(getattr(response, "headers", {}) or {}).get(
                        "Retry-After"
                    ),
                )
                continue

            raise NaiAPIError(self._describe_error(response))

        raise NaiAPIError(f"重试 {attempts} 次后仍失败：{last_error}")

    def _wait_before_retry(self, attempt, attempts, retry_after=None):
        """在下一次请求前退避，最后一次尝试后不等待。"""
        if attempt + 1 >= attempts:
            return
        delay = self._retry_delay(attempt, retry_after)
        if delay > 0:
            time.sleep(delay)

    def _retry_delay(self, attempt, retry_after=None):
        """解析上游建议的等待时间，异常时使用指数退避。"""
        try:
            if retry_after is not None:
                retry_after = float(retry_after)
                if math.isfinite(retry_after):
                    return min(30.0, max(0.0, retry_after))
        except (TypeError, ValueError):
            pass
        return min(30.0, self._retry_backoff * (2**attempt))

    def _extract_image(self, response):
        """从响应中取出图片字节，兼容 b64_json 与 url 两种返回。"""
        try:
            body = response.json()
        except ValueError:
            raise NaiAPIError("上游返回内容不是合法 JSON")

        if not isinstance(body, dict):
            raise NaiAPIError("上游返回结构不是 JSON 对象")
        data = body.get("data") or []
        if not data:
            raise NaiAPIError("上游未返回图片数据")
        if not isinstance(data, list) or not isinstance(data[0], dict):
            raise NaiAPIError("上游返回的图片数据结构无效")

        item = data[0]
        if item.get("b64_json"):
            try:
                decoded = base64.b64decode(item["b64_json"], validate=True)
            except (binascii.Error, TypeError, ValueError):
                raise NaiAPIError("上游返回的 Base64 图片无效")
            if not decoded:
                raise NaiAPIError("上游返回了空图片")
            return decoded
        if item.get("url"):
            try:
                fetched = requests.get(item["url"], timeout=self._timeout)
                fetched.raise_for_status()
                content = fetched.content
                if not content:
                    raise NaiAPIError("图片下载结果为空")
                return content
            except NaiAPIError:
                raise
            except requests.RequestException as exc:
                raise NaiAPIError(f"图片下载失败：{type(exc).__name__}")
        raise NaiAPIError("上游返回的数据项缺少图片内容")

    @staticmethod
    def _describe_error(response):
        """把上游错误转成用户能看懂的说明。"""
        detail = ""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                detail = error.get("message") or ""
            elif error:
                detail = str(error)
        except ValueError:
            detail = response.text[:150]

        code = response.status_code
        if code == 401:
            return "API 密钥无效或已过期"
        if code == 404:
            return "API 地址错误，端点不存在"
        if code == 400 and "size" in detail.lower():
            return f"尺寸不被支持：{detail}"
        return f"生成失败（HTTP {code}）：{detail or '无详细信息'}"
