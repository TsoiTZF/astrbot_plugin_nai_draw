"""NAI 上游客户端测试，不产生真实网络请求。"""

import base64
import sys
import types
from unittest.mock import patch

import requests

from nai_api import NaiAPI, NaiAPIError


_failures = []


def check(condition, label):
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b"", text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.content = content
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, BaseException):
            raise self._body
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_base64_success():
    print("Base64 图片：")
    image = b"fake-png"
    response = FakeResponse(
        body={"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]}
    )
    api = NaiAPI("http://example.test", "sk-test", "nai-test", retry_backoff=0)
    with patch("nai_api.requests.post", return_value=response) as post:
        result = api.generate("prompt", "negative", "832x832")
    check(result == image, "正确解码 Base64 图片")
    check(post.call_args.kwargs["json"]["size"] == "832x832", "请求携带尺寸")
    check(post.call_args.kwargs["json"]["negative_prompt"] == "negative", "请求携带负面词")


def test_url_success():
    print("URL 图片：")
    response = FakeResponse(body={"data": [{"url": "http://image.test/a.png"}]})
    image_response = FakeResponse(content=b"downloaded-png")
    api = NaiAPI("http://example.test/", "sk-test", "nai-test", retry_backoff=0)
    with patch("nai_api.requests.post", return_value=response), patch(
        "nai_api.requests.get", return_value=image_response
    ) as getter:
        result = api.generate("prompt", "negative", "832x832")
    check(result == b"downloaded-png", "成功下载 URL 图片")
    check(getter.call_args.args[0] == "http://image.test/a.png", "请求图片 URL")


def test_retry_and_timeout():
    print("重试和超时：")
    image = b"retry-success"
    success = FakeResponse(
        body={"data": [{"b64_json": base64.b64encode(image).decode("ascii")}]}
    )
    unavailable = FakeResponse(
        status_code=503,
        body={"error": {"message": "busy"}},
        headers={"Retry-After": "2.5"},
    )
    api = NaiAPI("http://example.test", "sk-test", "nai-test", retry_backoff=1)
    with patch(
        "nai_api.requests.post",
        side_effect=[requests.Timeout(), unavailable, success],
    ), patch("nai_api.time.sleep") as sleeper:
        result = api.generate("prompt", "negative", "832x832", retries=3)
    check(result == image, "超时和 503 后恢复成功")
    check(sleeper.call_count == 2, "仅在后续尝试前等待")
    check(sleeper.call_args_list[0].args[0] == 1, "超时使用指数退避")
    check(sleeper.call_args_list[1].args[0] == 2.5, "尊重 Retry-After")


def test_invalid_responses():
    print("异常响应：")
    api = NaiAPI("http://example.test", "sk-test", "nai-test", retry_backoff=0)
    cases = [
        (FakeResponse(body=ValueError("bad json")), "不是合法 JSON"),
        (FakeResponse(body={"data": []}), "未返回图片数据"),
        (FakeResponse(body={"data": [{"b64_json": "%%%"}]}), "Base64 图片无效"),
        (FakeResponse(body={"data": [{"url": "http://image.test/a.png"}]}), "图片下载失败"),
    ]
    for response, expected in cases:
        getter = patch(
            "nai_api.requests.get",
            side_effect=requests.ConnectionError("offline"),
        )
        with patch("nai_api.requests.post", return_value=response), getter:
            try:
                api.generate("prompt", "negative", "832x832", retries=1)
            except NaiAPIError as exc:
                check(expected in str(exc), f"{expected} 转为用户异常")
            except Exception as exc:
                check(False, f"异常未泄漏为 {type(exc).__name__}")
            else:
                check(False, f"应拒绝异常响应：{expected}")

    unauthorized = FakeResponse(
        status_code=401,
        body={"error": "invalid key"},
    )
    with patch("nai_api.requests.post", return_value=unauthorized):
        try:
            api.generate("prompt", "negative", "832x832", retries=1)
        except NaiAPIError as exc:
            check(str(exc) == "API 密钥无效或已过期", "401 映射为密钥错误")
        else:
            check(False, "401 应抛出密钥错误")


def test_configuration():
    print("客户端配置：")
    check(not NaiAPI("", "sk-test", "nai-test").configured, "缺少地址时未配置")
    check(not NaiAPI("http://example.test", "", "nai-test").configured, "缺少密钥时未配置")
    api = NaiAPI(
        "http://example.test/",
        " sk-test ",
        "",
        timeout=-1,
        retry_backoff=float("nan"),
    )
    check(api.configured, "完整配置可用")
    check(api._base == "http://example.test", "地址去掉尾斜杠")
    check(api._key == "sk-test" and api._timeout == 1, "密钥和超时被归一化")
    check(api._model == "nai-diffusion-4-5-full", "空模型回退默认值")
    check(api._retry_backoff == 1.0, "非法退避值回退默认值")


def main():
    print("=" * 56)
    print("NAI 绘画插件 API 客户端测试")
    print("=" * 56)
    for func in (
        test_base64_success,
        test_url_success,
        test_retry_and_timeout,
        test_invalid_responses,
        test_configuration,
    ):
        func()
        print()
    print("=" * 56)
    if _failures:
        print(f"失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
