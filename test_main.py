"""NAI 插件主流程测试，使用最小 AstrBot 桩，不启动真实 AstrBot。"""

import asyncio
import base64
import importlib
import io
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from PIL import Image

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
    component_module = types.ModuleType("astrbot.api.message_components")

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

    class FakePlain:
        def __init__(self, text):
            self.text = text

    class FakeImage:
        def __init__(self, file="", url="", path=""):
            self.file = file
            self.url = url
            self.path = path or file

        @classmethod
        def fromFileSystem(cls, path):
            return cls(file=path, path=path)

    class FakeFile:
        def __init__(self, name="", file="", url=""):
            self.name = name
            self.file = file
            self.url = url

        async def get_file(self, allow_return_url=False):
            return self.file or self.url

    class FakeReply:
        def __init__(self, chain=None):
            self.chain = list(chain or [])

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
    component_module.Plain = FakePlain
    component_module.Image = FakeImage
    component_module.File = FakeFile
    component_module.Reply = FakeReply
    sys.modules.update(
        {
            "astrbot": root,
            "astrbot.api": api,
            "astrbot.api.event": event_module,
            "astrbot.api.star": star_module,
            "astrbot.api.message_components": component_module,
        }
    )


class FakeEvent:
    def __init__(self, sender_id="user-1", message=None):
        self.sender_id = sender_id
        self.message_obj = types.SimpleNamespace(message=list(message or []))

    def get_sender_id(self):
        return self.sender_id

    def plain_result(self, text):
        return ("plain", text)

    def image_result(self, path):
        return ("image", path)

    def chain_result(self, chain):
        return ("chain", chain)


async def collect_draw_results(plugin, event, args):
    """收集绘图指令依次发出的进度与最终结果。"""
    return [result async for result in plugin.cmd_draw(event, args)]


def run_draw(plugin, event, args):
    return asyncio.run(collect_draw_results(plugin, event, args))


async def collect_random_results(plugin, event, args=""):
    """收集独立随机场景指令结果。"""
    return [result async for result in plugin.cmd_random_draw(event, args)]


async def collect_steg_results(plugin, event, args=""):
    return [result async for result in plugin.cmd_steg_extract(event, args)]


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
            "-风格 cinematic -尺寸 竖图 长发女孩"
        )
        check(text == "长发女孩", "参数从描述中移除")
        check(preset == "cinematic", "预设参数解析")
        check(size == "832x1216" and not warning, "合法中文尺寸不产生误报")

        text, preset, _, warning = plugin._parse_args("-风格 3 white dress")
        check(text == "white dress" and preset == "neon_flat", "数字预设参数解析")
        check(not warning, "合法数字预设不产生警告")

        text, preset, _, warning = plugin._parse_args("2 white dress")
        check(text == "white dress" and preset == "cinematic", "开头编号直接选择预设")
        check(not warning, "免参数数字选择不产生警告")

        text, preset, _, _ = plugin._parse_args("2girls, white dress")
        check(text.startswith("2girls") and preset == "iceblue", "标签数字不被误判为编号")

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
        check("1 = 冰蓝柔光（日系）" in preset_help[1], "预设清单显示数字与中文名")
        check("9 = 青雾胶片插画" in preset_help[1], "预设清单显示完整编号范围")

        selected = run_draw(plugin, event, "2")
        check(selected[0][0] == "plain" and "已选择" in selected[0][1], "单独编号选择成功")
        check(plugin._user_presets["user-preset"] == "cinematic", "个人预设已保存")
        check(not plugin._last_call, "选择命令不触发冷却")

        selected_help = asyncio.run(plugin.cmd_presets(event))
        check("你的选择：2 = 冷调电影厚涂" in selected_help[1], "清单显示个人选择编号")

        result = run_draw(plugin, event, "white dress")
        check(result[-1] == ("fake",), "后续描述进入生成流程")
        check("2 = 冷调电影厚涂" in result[0][1], "进度反馈显示个人预设")
        check("尺寸：832x1216" in result[0][1], "进度反馈显示实际尺寸")
        check("NSFW：关闭" in result[0][1], "进度反馈显示 NSFW 状态")
        check("自动脸型：开启" in result[0][1], "进度反馈显示自动脸型状态")
        check("个人画师：未设置" in result[0][1], "进度反馈显示个人画师状态")
        check(calls[-1][2] == "cinematic", "后续描述使用个人预设")

        run_draw(plugin, event, "3 night city")
        check(calls[-1][2] == "neon_flat", "一步式编号绘图使用对应预设")
        check(plugin._user_presets["user-preset"] == "neon_flat", "一步式绘图更新个人预设")

        run_draw(plugin, event, "9 mist portrait")
        check(calls[-1][2] == "filmgrain_illustration", "末尾编号使用青雾胶片预设")
        check(plugin._user_presets["user-preset"] == "filmgrain_illustration", "末尾编号更新个人预设")

        no_preset = run_draw(plugin, event, "0")
        check("已选择" in no_preset[0][1] and "无预设" in no_preset[0][1], "单独选择无预设成功")
        check(plugin._user_presets["user-preset"] == "none", "无预设个人选择已保存")

        run_draw(plugin, event, "0 night city")
        check(calls[-1][2] == "none", "一步式无预设绘图进入生成链路")

        invalid = run_draw(plugin, event, "10")
        check(invalid[0][0] == "plain" and "0~9" in invalid[0][1], "越界编号返回范围提示")

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

        invalid = run_draw(plugin, event, "10 white dress")
        check(invalid[0][0] == "plain" and "0~9" in invalid[0][1], "越界快捷编号被拒绝")
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
                    "iceblue",
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
                    "iceblue",
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


def test_stego_commands():
    print("隐写传输与提取指令：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(object(), {"keep_images": False})
        component_module = sys.modules["astrbot.api.message_components"]

        cover_path = plugin._cover_dir / "cover.png"
        Image.new("RGB", (48, 48), (90, 140, 190)).save(cover_path)
        generated_path = plugin._out_dir / "nai_test.png"
        Image.new("RGB", (24, 24), (220, 80, 120)).save(generated_path)

        user = FakeEvent("stego-user")
        password = "CaseSensitive-Secret"
        enabled = asyncio.run(plugin.cmd_steg_toggle(user, f"开 {password}"))
        status = asyncio.run(plugin.cmd_steg_toggle(user, "状态"))
        check("已设置密码" in enabled[1], "开启隐写时确认已设置密码")
        check(password not in enabled[1] and password not in status[1], "聊天结果不回显密码")
        check(plugin._steg_password["stego-user"] == password, "密码大小写原样保留")

        hidden = asyncio.run(
            plugin._hide_into_cover(user, generated_path, "stego-user", "none")
        )
        check(hidden[0] == "chain", "隐写结果使用复合消息反馈")
        chain = hidden[1]
        file_segments = [
            item for item in chain if isinstance(item, component_module.File)
        ]
        check(len(file_segments) == 1, "隐写 PNG 以原始文件组件发送")
        check(
            any(isinstance(item, component_module.Image) for item in chain),
            "同时发送明确标注的载体预览",
        )
        stego_path = Path(file_segments[0].file)
        check(stego_path.is_file(), "发送前保留服务器隐写原图")
        check(plugin._last_stego["stego-user"] == str(stego_path), "记录个人最近隐写原图")

        latest = asyncio.run(collect_steg_results(plugin, user, "最近"))
        check(latest[0][0] == "plain" and "正在提取" in latest[0][1], "最近提取先反馈进度")
        check(latest[-1][0] == "image", "无需回传文件即可提取最近一次")

        reply = component_module.Reply(
            [
                component_module.Image(url=str(cover_path)),
                component_module.File(name=stego_path.name, file=str(stego_path)),
            ]
        )
        replied = asyncio.run(
            collect_steg_results(
                plugin,
                FakeEvent("stego-user", [reply]),
                password,
            )
        )
        check(replied[-1][0] == "image", "引用同时含预览和文件时优先提取原始文件")

        corrupted = asyncio.run(
            collect_steg_results(
                plugin,
                FakeEvent(
                    "stego-user",
                    [component_module.Image(url=str(cover_path))],
                ),
            )
        )
        check(
            corrupted[-1][0] == "plain"
            and "QQ 会压缩图片" in corrupted[-1][1],
            "普通图片提取失败时说明平台压缩原因",
        )

        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), (12, 34, 56)).save(buffer, "PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        added = asyncio.run(
            plugin.cmd_add_cover(
                FakeEvent(
                    "stego-user",
                    [component_module.Image(url=f"base64://{encoded}")],
                ),
                "../新增载体",
            )
        )
        check(added[0] == "plain" and "[成功]" in added[1], "异步下载链路可直接添加载体")
        check((plugin._cover_dir / "新增载体.png").is_file(), "自定义载体名限制在图库目录")

        asyncio.run(plugin.terminate())
        check(not plugin._last_stego, "插件卸载时清理最近隐写记录")


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
            plugin._generate_and_send(event, "1girl", "iceblue", "832x832", "")
        )
        check(result[0] == "plain" and "上游失败" in result[1], "上游失败返回可读提示")
        check(not plugin._last_call, "失败后释放冷却状态")


def test_random_scene_command():
    print("独立随机场景指令：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(
            object(),
            {"api_base": "http://example.test", "api_key": "sk-test", "cooldown": 0},
        )
        event = FakeEvent("user-random")
        captured = []

        async def fake_generate(*args):
            captured.append(args)
            return ("fake-random",)

        plugin._generate_and_send = fake_generate
        scene = {
            "title": "测试法典场景",
            "prompt": "sitting in a wooden boat, 1.2::medium shot::",
            "entry_id": "composition_style_test",
        }
        with patch("astrbot_plugin_nai_draw.main.composition_scene", return_value=scene):
            result = asyncio.run(collect_random_results(plugin, event))

        check("测试法典场景" in result[0][1], "随机指令反馈场景标题")
        check(result[-1] == ("fake-random",), "随机指令进入统一生成链路")
        check(captured[-1][1] == scene["prompt"], "随机指令使用完整法典场景串")
        check(captured[-1][2] == "iceblue", "随机指令继承默认预设")

        with patch("astrbot_plugin_nai_draw.main.composition_scene", return_value=scene):
            result = asyncio.run(
                collect_random_results(plugin, event, "-风格 4 -尺寸 横图")
            )
        check(captured[-1][2] == "glossy_mature", "随机指令支持画风参数")
        check(captured[-1][3] == "1216x832", "随机指令支持尺寸参数")
        check("4 = 高光成熟人物" in result[0][1], "随机反馈显示实际画风")


def test_variant_rotation():
    print("脸型组合轮换：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_cls = load_plugin(temp_dir)
        plugin = plugin_cls(object(), {})
        preset_module = importlib.import_module("astrbot_plugin_nai_draw.presets")
        count = preset_module.variant_count("iceblue")

        with patch("astrbot_plugin_nai_draw.main.random.randrange", return_value=0):
            indexes = [
                plugin._next_variant_index("user-a", "iceblue")
                for _ in range(count + 1)
            ]
            other_first = plugin._next_variant_index("user-b", "iceblue")

        check(indexes[:-1] == list(range(count)), "完整周期按顺序遍历且不重复")
        check(indexes[-1] == 0, "周期结束后回到首个组合")
        check(other_first == 0, "不同用户拥有独立轮换状态")

        combinations = [
            preset_module.pick_variant("iceblue", index=index)
            for index in indexes
        ]
        check(
            all(
                left[0] != right[0] or left[1] != right[1] or left[2] != right[2]
                for left, right in zip(combinations, combinations[1:])
            ),
            "生产轮换相邻组合至少一个维度不同",
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
        test_stego_commands,
        test_failure_releases_cooldown,
        test_random_scene_command,
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
