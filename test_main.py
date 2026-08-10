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
                "enable_face_variation": "false",
                "keep_images": "true",
                "timeout": "bad",
                "max_concurrent": "0",
            },
        )
        check(plugin._use_llm_translate() is False, "字符串 false 不会被误判为真")
        check(plugin._bool_config("allow_nsfw") is False, "数字字符串 0 解析为假")
        check(plugin._face_variation_enabled() is False, "自动脸型字符串 false 生效")
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
        check("0 = 无预设" in preset_help[1], "预设清单显示 0 号无预设")
        check("/nai画师 添加" in preset_help[1], "预设清单显示个人画师入口")
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
        check("自动脸型：开启" in result[0][1], "进度反馈显示自动脸型状态")
        check("个人画师：未设置" in result[0][1], "进度反馈显示个人画师状态")
        check(calls[-1][2] == "hiten", "后续描述使用个人预设")

        run_draw(plugin, event, "3 night city")
        check(calls[-1][2] == "pop", "一步式编号绘图使用对应预设")
        check(plugin._user_presets["user-preset"] == "pop", "一步式绘图更新个人预设")

        no_preset = run_draw(plugin, event, "0")
        check("已选择" in no_preset[0][1] and "无预设" in no_preset[0][1], "单独选择无预设成功")
        check(plugin._user_presets["user-preset"] == "none", "无预设个人选择已保存")

        run_draw(plugin, event, "0 night city")
        check(calls[-1][2] == "none", "一步式无预设绘图进入生成链路")

        invalid = run_draw(plugin, event, "9")
        check(invalid[0][0] == "plain" and "0~8" in invalid[0][1], "越界编号返回范围提示")

        asyncio.run(plugin.terminate())
        check(not plugin._user_presets, "插件卸载时清理个人预设")


def test_input_validation_and_feedback():
    print("输入校验与转换反馈：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {"api_base": "http://example.test", "api_key": "sk-test", "cooldown": 30},
        )
        event = FakeEvent("user-input")
        calls = []

        async def fake_generate(*args):
            calls.append(args)
            return ("fake",)

        plugin._generate_and_send = fake_generate

        invalid = run_draw(plugin, event, "9 white dress")
        check(invalid[0][0] == "plain" and "0~8" in invalid[0][1], "越界快捷编号被拒绝")
        check(not calls and "user-input" not in plugin._user_presets, "越界编号不生成也不保存")

        async def no_tags(*args, **kwargs):
            return "", "未能识别中文描述，请改用英文标签"

        with patch("astrbot_plugin_nai_draw.main.to_tags", new=no_tags):
            failed = run_draw(plugin, event, "青龙偃月刀")
        check("指令已生效" in failed[0][1], "转换前仍即时反馈指令状态")
        check(failed[-1][0] == "plain" and "改用英文" in failed[-1][1], "无可用标签时返回明确失败")
        check(not calls, "无可用标签时不调用生成链路")
        check("user-input" not in plugin._last_call, "转换失败后释放冷却")

        async def translated_with_note(*args, **kwargs):
            return "1girl, long hair", "未识别部分已忽略：青龙偃月刀"

        with patch(
            "astrbot_plugin_nai_draw.main.to_tags", new=translated_with_note
        ):
            result = run_draw(plugin, event, "长发女孩拿着青龙偃月刀")
        check(result[1][0] == "plain" and result[1][1].startswith("[提示]"), "转换说明反馈给用户")
        check(result[-1] == ("fake",), "有可用标签时继续生成")
        check(calls[-1][1] == "1girl, long hair", "生成链路使用转换后的标签")

        plugin._last_call.clear()
        fallback = run_draw(plugin, event, "-尺寸 999x999 1girl")
        check("尺寸 999x999 不可用" in fallback[1][1], "参数回退说明反馈给用户")
        check(fallback[-1] == ("fake",) and calls[-1][3] == "832x1216", "参数回退后使用实际尺寸生成")


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

        def fake_build_negative(
            preset_key,
            allow_nsfw,
            extra,
            face_negative="",
            user_text="",
            include_face=True,
        ):
            captured["allow_nsfw"] = allow_nsfw
            captured["face_negative"] = face_negative
            captured["user_text"] = user_text
            captured["include_face"] = include_face
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
        check(captured.get("include_face") is True, "默认生成链路启用自动脸型")
        # 五官排他负面词须一路传到负面词组装，否则脸型分化失效
        check(bool(captured.get("face_negative")), "生成链路透传五官排他负面词")
        check(captured.get("user_text") == "1girl", "生成链路透传用户描述用于冲突剔除")

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


def test_face_variation_command():
    print("个人自动脸型指令：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {
                "api_base": "http://example.test",
                "api_key": "sk-test",
                "cooldown": 0,
                "enable_face_variation": True,
            },
        )
        user = FakeEvent("user-face")

        help_result = run_draw(plugin, user, "")
        check("/nai脸型" in help_result[0][1], "绘图帮助显示自动脸型指令")
        check("/nai 0" in help_result[0][1], "绘图帮助显示无预设入口")
        check("/nai画师 添加" in help_result[0][1], "绘图帮助显示个人画师入口")

        status = asyncio.run(plugin.cmd_face_variation(user))
        check("开启" in status[1] and "管理面板默认" in status[1], "默认状态正确")

        closed = asyncio.run(plugin.cmd_face_variation(user, "关"))
        check(closed[0] == "plain" and "已关闭" in closed[1], "关闭指令成功")
        check(plugin._face_variation_enabled("user-face") is False, "个人关闭状态生效")
        check(plugin._face_variation_enabled("other-user") is True, "个人设置不影响其他用户")

        captured = {}
        plugin._api = types.SimpleNamespace(
            configured=True,
            generate=lambda *args, **kwargs: b"fake-image"
        )

        def fake_build_prompt(
            preset_key,
            user_text,
            year_tag="year 2024",
            index=None,
            include_face=True,
            custom_artist="",
        ):
            captured["include_face"] = include_face
            return "prompt", ""

        with patch(
            "astrbot_plugin_nai_draw.main.build_prompt",
            side_effect=fake_build_prompt,
        ):
            asyncio.run(
                plugin._generate_and_send(
                    user,
                    "1girl",
                    "laowuyang",
                    "832x832",
                    "",
                    sender_id="user-face",
                )
            )
        check(captured.get("include_face") is False, "生成链路关闭自动脸型注入")

        async def fake_generate(*args):
            return ("fake",)

        plugin._generate_and_send = fake_generate
        result = run_draw(plugin, user, "1girl")
        check("自动脸型：关闭" in result[0][1], "进度反馈显示个人关闭状态")

        opened = asyncio.run(plugin.cmd_face_variation(user, "开"))
        check("已开启" in opened[1] and plugin._face_variation_enabled("user-face"), "开启指令成功")

        plugin.config["enable_face_variation"] = False
        reset = asyncio.run(plugin.cmd_face_variation(user, "默认"))
        check("管理面板默认值：关闭" in reset[1], "恢复管理面板关闭状态")
        check("user-face" not in plugin._user_face_variation, "恢复默认后删除个人覆盖")

        invalid = asyncio.run(plugin.cmd_face_variation(user, "未知"))
        check("用法" in invalid[1], "非法参数返回用法")

        asyncio.run(plugin.cmd_face_variation(user, "开"))
        asyncio.run(plugin.terminate())
        check(not plugin._user_face_variation, "插件卸载时清理自动脸型设置")


def test_artist_command():
    print("个人画师串指令：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {
                "api_base": "http://example.test",
                "api_key": "sk-test",
                "cooldown": 0,
            },
        )
        user = FakeEvent("user-artist")
        other = FakeEvent("other-artist")

        status = asyncio.run(plugin.cmd_artists(user))
        check("未设置" in status[1], "默认没有个人画师串")

        direct = asyncio.run(plugin.cmd_artists(user, "wlop"))
        check("已添加" in direct[1], "直接发送英文画师名可追加")
        check(plugin._artist_tags("user-artist") == ("artist:wlop",), "裸名称自动补画师前缀")

        added = asyncio.run(
            plugin.cmd_artists(
                user,
                "添加 {artist:guweiz}, 2.0::artist:bad::",
            )
        )
        check("忽略 1 个" in added[1], "添加时提示无效权重标签")
        check(
            plugin._artist_tags("user-artist")
            == ("artist:wlop", "{artist:guweiz}"),
            "合法画师按顺序追加",
        )
        check(not plugin._artist_tags("other-artist"), "个人画师串不影响其他用户")

        listed = asyncio.run(plugin.cmd_artists(user, "状态"))
        check("1. artist:wlop" in listed[1], "状态按编号显示画师串")
        check("2. {artist:guweiz}" in listed[1], "状态显示全部画师串")

        deleted = asyncio.run(plugin.cmd_artists(user, "删除 1"))
        check("artist:wlop" in deleted[1], "按编号删除画师成功")
        check(plugin._artist_tags("user-artist") == ("{artist:guweiz}",), "删除后保留其他画师")

        replaced = asyncio.run(
            plugin.cmd_artists(user, "设置 1.2::artist:sakimichan::")
        )
        check("已设置" in replaced[1], "设置指令替换原画师串")
        check(
            plugin._artist_tags("user-artist")
            == ("1.2::artist:sakimichan::",),
            "设置后只保留新画师串",
        )

        invalid = asyncio.run(plugin.cmd_artists(user, "添加 普通中文描述"))
        check(invalid[0] == "plain" and "没有合法" in invalid[1], "非法画师串被拒绝")
        check(len(plugin._artist_tags("user-artist")) == 1, "非法输入不覆盖已有画师")

        captured = {}
        plugin._api = types.SimpleNamespace(
            configured=True,
            generate=lambda *args, **kwargs: b"fake-image",
        )

        def fake_build_prompt(
            preset_key,
            user_text,
            year_tag="year 2024",
            index=None,
            include_face=True,
            custom_artist="",
        ):
            captured["custom_artist"] = custom_artist
            return "prompt", ""

        with patch(
            "astrbot_plugin_nai_draw.main.build_prompt",
            side_effect=fake_build_prompt,
        ):
            asyncio.run(
                plugin._generate_and_send(
                    user,
                    "1girl",
                    "none",
                    "832x832",
                    "",
                    sender_id="user-artist",
                )
            )
        check(
            captured.get("custom_artist") == "1.2::artist:sakimichan::",
            "生成链路透传个人画师串",
        )

        async def fake_generate(*args):
            return ("fake",)

        plugin._generate_and_send = fake_generate
        result = run_draw(plugin, user, "0 1girl")
        check("预设：0 = 无预设" in result[0][1], "进度反馈显示无预设模式")
        check("个人画师：1 个" in result[0][1], "进度反馈显示个人画师数量")

        cleared = asyncio.run(plugin.cmd_artists(user, "清空"))
        check("已清空" in cleared[1] and not plugin._artist_tags("user-artist"), "清空画师串成功")

        asyncio.run(plugin.cmd_artists(user, "artist:wlop"))
        asyncio.run(plugin.terminate())
        check(not plugin._user_artists, "插件卸载时清理个人画师串")


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


def test_variant_rotation():
    print("脸型组合轮换：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(object(), {})
        preset_module = importlib.import_module("astrbot_plugin_nai_draw.presets")
        count = preset_module.variant_count("laowuyang")

        with patch("astrbot_plugin_nai_draw.main.random.randrange", return_value=0):
            indexes = [
                plugin._next_variant_index("user-a", "laowuyang")
                for _ in range(count + 1)
            ]
            other_first = plugin._next_variant_index("user-b", "laowuyang")

        check(indexes[:-1] == list(range(count)), "完整周期按顺序遍历且不重复")
        check(indexes[-1] == 0, "周期结束后回到首个组合")
        check(other_first == 0, "不同用户拥有独立轮换状态")

        combinations = [
            preset_module.pick_variant("laowuyang", index=index)
            for index in indexes
        ]
        check(
            all(
                left[0] != right[0] and left[1] != right[1]
                for left, right in zip(combinations, combinations[1:])
            ),
            "生产轮换相邻画师和五官均不同",
        )

        asyncio.run(plugin.terminate())
        check(not plugin._variant_positions, "插件卸载时清理轮换状态")


def main():
    print("=" * 56)
    print("NAI 绘画插件主流程测试")
    print("=" * 56)
    for func in (
        test_config_and_parse,
        test_cooldown_reservation,
        test_personal_preset_selection,
        test_input_validation_and_feedback,
        test_nsfw_command,
        test_face_variation_command,
        test_artist_command,
        test_failure_releases_cooldown,
        test_variant_rotation,
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
