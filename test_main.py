"""NAI 插件主流程测试，使用最小 AstrBot 桩，不启动真实 AstrBot。"""

import asyncio
import importlib
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

_failures = []


def check(condition, label):
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


def install_astrbot_stub(data_dir):
    root = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    star_module = types.ModuleType("astrbot.api.star")

    class FakeFilter:
        @staticmethod
        def command(*args, **kwargs):
            return lambda func: func

    class FakeStar:
        def __init__(self, context):
            self.context = context

    class FakeStarTools:
        @staticmethod
        def get_data_dir(name):
            return Path(data_dir)

    def register(*args, **kwargs):
        return lambda cls: cls

    logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    root.api = api
    api.logger = logger
    api.event = event_module
    api.star = star_module
    event_module.filter = FakeFilter
    event_module.AstrMessageEvent = object
    star_module.Context = object
    star_module.Star = FakeStar
    star_module.StarTools = FakeStarTools
    star_module.register = register
    sys.modules.update(
        {
            "astrbot": root,
            "astrbot.api": api,
            "astrbot.api.event": event_module,
            "astrbot.api.star": star_module,
        }
    )


class FakeEvent:
    def __init__(self, sender_id="user-1"):
        self.sender_id = sender_id

    def get_sender_id(self):
        return self.sender_id

    def plain_result(self, text):
        return ("plain", text)

    def image_result(self, path):
        return ("image", path)


async def collect_draw_results(plugin, event, args):
    """收集绘图指令依次发出的进度与最终结果。"""
    return [result async for result in plugin.cmd_draw(event, args)]


def run_draw(plugin, event, args):
    return asyncio.run(collect_draw_results(plugin, event, args))


class FailingAPI:
    def __init__(self, error_type):
        self._error_type = error_type

    def generate(self, *args, **kwargs):
        raise self._error_type("上游失败")


def load_plugin(temp_dir):
    install_astrbot_stub(temp_dir)
    package = types.ModuleType("astrbot_plugin_nai_draw")
    package.__path__ = [str(Path(__file__).parent)]
    sys.modules[package.__name__] = package
    return importlib.import_module("astrbot_plugin_nai_draw.main").NaiDrawPlugin


def test_config_and_parse():
    print("配置和参数解析：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {
                "api_base": "http://example.test",
                "api_key": "sk-test",
                "llm_translate": "false",
                "allow_nsfw": "0",
                "keep_images": "true",
                "timeout": "bad",
                "max_concurrent": "0",
            },
        )
        check(plugin._use_llm_translate() is False, "字符串 false 不会被误判为真")
        check(plugin._bool_config("allow_nsfw") is False, "数字字符串 0 解析为假")
        check(plugin._bool_config("keep_images") is True, "字符串 true 解析为真")
        check(plugin._api._timeout == 180, "非法超时回退默认值")
        plugin.config["model"] = ""
        check(
            plugin._build_api()._model == "nai-diffusion-4-5-full",
            "空模型回退默认值",
        )
        check(plugin._max_concurrent() == 1, "并发数下限生效")

        text, preset, size, warning = plugin._parse_args(
            "-风格 hiten -尺寸 竖图 长发女孩"
        )
        check(text == "长发女孩", "参数从描述中移除")
        check(preset == "hiten", "预设参数解析")
        check(size == "832x1216" and not warning, "合法中文尺寸不产生误报")

        text, preset, _, warning = plugin._parse_args("-风格 3 white dress")
        check(text == "white dress" and preset == "pop", "数字预设参数解析")
        check(not warning, "合法数字预设不产生警告")

        text, preset, _, warning = plugin._parse_args("2 white dress")
        check(text == "white dress" and preset == "hiten", "开头编号直接选择预设")
        check(not warning, "免参数数字选择不产生警告")

        text, preset, _, _ = plugin._parse_args("2girls, white dress")
        check(text.startswith("2girls") and preset == "laowuyang", "标签数字不被误判为编号")

        _, _, fallback_size, warning = plugin._parse_args("-尺寸 999x999 red hair")
        check(fallback_size == "832x1216", "非法尺寸回退默认")
        check("不可用" in warning, "非法尺寸给出提示")


def test_cooldown_reservation():
    print("冷却预约：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {"api_base": "http://example.test", "api_key": "sk-test", "cooldown": 30},
        )
        event = FakeEvent()
        calls = []

        async def fake_generate(*args):
            calls.append(args)
            return ("fake",)

        plugin._generate_and_send = fake_generate
        first = run_draw(plugin, event, "1girl")
        second = run_draw(plugin, event, "1girl")
        check(first[-1] == ("fake",), "首次命令进入生成流程")
        check("指令已生效" in first[0][1], "生成前立即返回进度反馈")
        check(second[0][0] == "plain" and "冷却中" in second[0][1], "重复命令被冷却拦截")
        check(len(calls) == 1, "冷却期间只生成一次")


def test_personal_preset_selection():
    print("个人预设选择：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {"api_base": "http://example.test", "api_key": "sk-test", "cooldown": 0},
        )
        event = FakeEvent("user-preset")
        calls = []

        async def fake_generate(*args):
            calls.append(args)
            return ("fake",)

        plugin._generate_and_send = fake_generate
        preset_help = asyncio.run(plugin.cmd_presets(event))
        check("1 = 老五样" in preset_help[1], "预设清单显示数字与中文名")
        check("8 = 厚涂油画" in preset_help[1], "预设清单显示完整编号范围")

        selected = run_draw(plugin, event, "2")
        check(selected[0][0] == "plain" and "已选择" in selected[0][1], "单独编号选择成功")
        check(plugin._user_presets["user-preset"] == "hiten", "个人预设已保存")
        check(not plugin._last_call, "选择命令不触发冷却")

        selected_help = asyncio.run(plugin.cmd_presets(event))
        check("你的选择：2 = hiten 柔和日系" in selected_help[1], "清单显示个人选择编号")

        result = run_draw(plugin, event, "white dress")
        check(result[-1] == ("fake",), "后续描述进入生成流程")
        check("2 = hiten 柔和日系" in result[0][1], "进度反馈显示个人预设")
        check("尺寸：832x1216" in result[0][1], "进度反馈显示实际尺寸")
        check("NSFW：关闭" in result[0][1], "进度反馈显示 NSFW 状态")
        check(calls[-1][2] == "hiten", "后续描述使用个人预设")

        run_draw(plugin, event, "3 night city")
        check(calls[-1][2] == "pop", "一步式编号绘图使用对应预设")
        check(plugin._user_presets["user-preset"] == "pop", "一步式绘图更新个人预设")

        invalid = run_draw(plugin, event, "9")
        check(invalid[0][0] == "plain" and "1~8" in invalid[0][1], "越界编号返回范围提示")

        asyncio.run(plugin.terminate())
        check(not plugin._user_presets, "插件卸载时清理个人预设")


def test_nsfw_command():
    print("个人 NSFW 指令：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(object(), {"allow_nsfw": False})
        user = FakeEvent("user-nsfw")
        other = FakeEvent("other-user")

        status = asyncio.run(plugin.cmd_nsfw(user))
        check("关闭" in status[1] and "管理面板默认" in status[1], "默认状态正确")

        opened = asyncio.run(plugin.cmd_nsfw(user, "开"))
        check(opened[0] == "plain" and "已开启" in opened[1], "开启指令成功")
        check(plugin._allow_nsfw("user-nsfw") is True, "个人开启状态生效")
        check(plugin._allow_nsfw("other-user") is False, "个人设置不影响其他用户")

        captured = {}
        plugin._api = types.SimpleNamespace(
            generate=lambda *args, **kwargs: b"fake-image"
        )

        def fake_build_negative(preset_key, allow_nsfw, extra):
            captured["allow_nsfw"] = allow_nsfw
            return "negative"

        with patch(
            "astrbot_plugin_nai_draw.main.build_negative",
            side_effect=fake_build_negative,
        ):
            asyncio.run(
                plugin._generate_and_send(
                    user,
                    "1girl",
                    "laowuyang",
                    "832x832",
                    "",
                    sender_id="user-nsfw",
                )
            )
        check(captured.get("allow_nsfw") is True, "生成链路使用个人开启状态")

        closed = asyncio.run(plugin.cmd_nsfw(user, "关"))
        check("已关闭" in closed[1] and plugin._allow_nsfw("user-nsfw") is False, "关闭指令成功")

        reset = asyncio.run(plugin.cmd_nsfw(user, "默认"))
        check("管理面板默认值" in reset[1], "恢复默认指令成功")
        check("user-nsfw" not in plugin._user_nsfw, "恢复默认后删除个人覆盖")

        invalid = asyncio.run(plugin.cmd_nsfw(user, "未知"))
        check("用法" in invalid[1], "非法参数返回用法")

        asyncio.run(plugin.cmd_nsfw(user, "开"))
        asyncio.run(plugin.terminate())
        check(not plugin._user_nsfw, "插件卸载时清理 NSFW 设置")


def test_failure_releases_cooldown():
    print("失败恢复：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {"api_base": "http://example.test", "api_key": "sk-test", "cooldown": 30},
        )
        error_type = importlib.import_module(
            "astrbot_plugin_nai_draw.nai_api"
        ).NaiAPIError
        plugin._api = FailingAPI(error_type)
        event = FakeEvent("user-fail")
        result = asyncio.run(
            plugin._generate_and_send(event, "1girl", "laowuyang", "832x832", "")
        )
        check(result[0] == "plain" and "上游失败" in result[1], "上游失败返回可读提示")
        check(not plugin._last_call, "失败后释放冷却状态")


def main():
    print("=" * 56)
    print("NAI 绘画插件主流程测试")
    print("=" * 56)
    for func in (
        test_config_and_parse,
        test_cooldown_reservation,
        test_personal_preset_selection,
        test_nsfw_command,
        test_failure_releases_cooldown,
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
