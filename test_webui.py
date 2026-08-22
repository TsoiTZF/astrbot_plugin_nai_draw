"""绘台 WebUI 测试，不启动 AstrBot，也不请求真实 NAI。"""

import asyncio
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


class FakeUpload:
    def __init__(self, filename, data):
        self.filename = filename
        self._data = data

    async def save(self, destination):
        Path(destination).write_bytes(self._data)

    async def read(self, size=-1):
        return self._data


class FakeContext:
    def __init__(self):
        self.registered = []

    def register_web_api(self, route, handler, methods, desc):
        self.registered.append((route, handler, methods, desc))


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
            "astrbot.api.message_components": component_module,
        }
    )


def load_plugin(temp_dir):
    for name in list(sys.modules):
        if name == "astrbot_plugin_nai_draw" or name.startswith(
            "astrbot_plugin_nai_draw."
        ):
            sys.modules.pop(name, None)
    install_astrbot_stub(temp_dir)
    package = types.ModuleType("astrbot_plugin_nai_draw")
    package.__path__ = [str(Path(__file__).parent)]
    sys.modules[package.__name__] = package
    return importlib.import_module("astrbot_plugin_nai_draw.main").NaiDrawPlugin


def png_bytes(color=(12, 34, 56), size=(24, 24)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def configured_plugin(temp_dir, context=None, extra_unconfigured=False, **extra):
    config = {
        "api_base": "" if extra_unconfigured else "http://example.test",
        "api_key": "" if extra_unconfigured else "sk-test",
        "cooldown": 0,
        "llm_translate": False,
        "keep_images": True,
    }
    config.update(extra)
    plugin_cls = load_plugin(temp_dir)
    plugin = plugin_cls(context or FakeContext(), config)
    if plugin._api.configured:
        plugin._api.generate = lambda *args, **kwargs: png_bytes()
    return plugin


def test_route_registration():
    print("路由注册：")
    with tempfile.TemporaryDirectory() as temp_dir:
        context = FakeContext()
        plugin = configured_plugin(temp_dir, context)
        routes = [item[0] for item in context.registered]
        check(hasattr(plugin, "_webui"), "插件挂上绘台对象")
        check(
            "/nai_draw/bootstrap" in routes
            and "/astrbot_plugin_nai_draw/bootstrap" in routes,
            "同时注册短名和目录名前缀",
        )
        check("/nai_draw/generate" in routes, "注册出图接口")
        check("/nai_draw/covers/upload" in routes, "注册载体上传接口")
        check("/nai_draw/extract/prepare" in routes, "注册提取密码接口")


def test_bootstrap_and_gallery():
    print("启动数据与样张墙：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin = configured_plugin(temp_dir)
        Image.new("RGB", (16, 16), (9, 8, 7)).save(plugin._out_dir / "nai_hiten_1.png")
        Image.new("RGB", (16, 16), (1, 2, 3)).save(plugin._cover_dir / "cover.png")
        data = asyncio.run(plugin._webui.bootstrap())
        check(data["configured"] is True, "已配置时启动数据标记接通")
        check(data["presets"][0]["key"] == "none", "预设清单含 0 号无预设")
        check(len(data["presets"]) == 9, "预设清单覆盖 0～8")
        check(data["gallery"][0]["preset"] == "hiten", "样张墙解析预设键")
        check(data["covers"][0]["name"] == "cover.png", "载体柜列出已有图片")

        empty = configured_plugin(temp_dir, extra_unconfigured=True)
        empty._api._base = ""
        empty._api._key = ""
        boot = asyncio.run(empty._webui.bootstrap())
        check(boot["configured"] is False, "未配置时启动数据给出断开状态")


def test_generate_success_and_validation():
    print("出图与校验：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin = configured_plugin(temp_dir)

        async def fake_tags(*args, **kwargs):
            return "1girl, long hair", ""

        with patch("astrbot_plugin_nai_draw.webui.to_tags", new=fake_tags):
            result = asyncio.run(
                plugin._webui.generate(
                    {
                        "prompt": "长发女孩",
                        "preset": "2",
                        "size": "方图",
                        "artists": "wlop",
                        "nsfw": True,
                        "face_variation": False,
                    }
                )
            )
        check(result["preset"] == "hiten", "数字预设 2 解析为 hiten")
        check(result["size"] == "832x832", "中文尺寸解析为方图")
        check(result["nsfw"] is True, "页面 NSFW 开关写入个人状态")
        check(result["face_variation"] is False, "页面自动脸型开关写入个人状态")
        check(result["artists"] == ["artist:wlop"], "裸画师名补前缀")
        check(result["image"]["data"], "返回 Base64 样张")
        check((plugin._out_dir / result["name"]).is_file(), "样张落到输出目录")

        missing = asyncio.run(plugin._webui.generate({"prompt": ""}))
        check(missing["status"] == "error" and "画面描述" in missing["message"], "空描述被拒绝")

        unknown = asyncio.run(
            plugin._webui.generate({"prompt": "1girl", "preset": "not-a-preset"})
        )
        check(unknown["status"] == "error" and "未知预设" in unknown["message"], "未知预设被拒绝")

        async def no_tags(*args, **kwargs):
            return "", "未能识别中文描述，请改用英文标签"

        with patch("astrbot_plugin_nai_draw.webui.to_tags", new=no_tags):
            failed = asyncio.run(plugin._webui.generate({"prompt": "青龙偃月刀"}))
        check("改用英文" in failed["message"], "无可用标签时返回明确失败")

        plugin._api._base = ""
        unconfigured = asyncio.run(plugin._webui.generate({"prompt": "1girl"}))
        check("未配置" in unconfigured["message"], "未配置 API 时拒绝出图")


def test_path_guard_and_covers():
    print("路径守卫与载体柜：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin = configured_plugin(temp_dir)
        ui = plugin._webui
        check(ui._safe_filename("../secret.png") == "secret.png", "路径只保留文件名")
        check(ui._safe_filename("..\\secret.png") == "secret.png", "反斜杠路径被截断")
        check(ui._safe_filename("foo/bar.png") == "bar.png", "子路径被截断")
        check(ui._safe_filename("新增载体.png") == "新增载体.png", "允许中文载体名")
        check(ui._safe_filename("note.txt") is None, "拒绝非图片扩展名")
        check(ui._safe_filename("a<>.png") is None, "拒绝非法文件名字符")

        outside = Path(temp_dir) / "outside.png"
        Image.new("RGB", (8, 8), (1, 1, 1)).save(outside)
        missing = asyncio.run(ui.preview({"name": "outside.png"}))
        check(missing["status"] == "error", "目录外文件不能预览")

        uploaded = asyncio.run(
            ui.upload_cover(
                FakeUpload("新增载体.png", png_bytes((90, 140, 190), (32, 32)))
            )
        )
        check(uploaded["name"] == "新增载体.png", "中文载体名可入库")
        check((plugin._cover_dir / "新增载体.png").is_file(), "载体文件落在图库目录")

        deleted = asyncio.run(ui.delete_cover({"name": "新增载体.png"}))
        check(deleted["deleted"] == "新增载体.png", "载体可删除")
        check(not (plugin._cover_dir / "新增载体.png").exists(), "删除后文件消失")

        empty = asyncio.run(ui.upload_cover(None))
        check(empty["status"] == "error" and "请选择" in empty["message"], "缺少文件时拒绝上传")


def test_stego_and_extract():
    print("隐写与拆封：")
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin = configured_plugin(temp_dir)
        Image.new("RGB", (48, 48), (90, 140, 190)).save(plugin._cover_dir / "cover.png")

        async def fake_tags(*args, **kwargs):
            return "1girl", ""

        with patch("astrbot_plugin_nai_draw.webui.to_tags", new=fake_tags):
            result = asyncio.run(
                plugin._webui.generate(
                    {
                        "prompt": "1girl",
                        "preset": "none",
                        "stego": True,
                        "stego_password": "CaseSensitive-Secret",
                    }
                )
            )
        check(result["stego"]["ok"] is True, "开启隐写时生成载体封装")
        check(result["stego"]["encrypted"] is True, "密码标记为已加密")
        check("CaseSensitive-Secret" not in str(result), "响应不回显隐写密码")
        stego_path = plugin._steg_dir / result["stego"]["name"]
        check(stego_path.is_file(), "隐写 PNG 保存在服务器")

        prepared = asyncio.run(
            plugin._webui.prepare_extract({"password": "CaseSensitive-Secret"})
        )
        check(prepared["has_password"] is True, "拆封前可暂存密码")
        extracted = asyncio.run(
            plugin._webui.extract(FakeUpload(stego_path.name, stego_path.read_bytes()))
        )
        check(extracted["image"]["data"], "原始隐写 PNG 可拆出生成图")

        wrong = asyncio.run(
            plugin._webui.extract(
                {
                    "password": "wrong",
                    "file": FakeUpload(stego_path.name, stego_path.read_bytes()),
                }
            )
        )
        check(wrong["status"] == "error", "错误密码时拆封失败")


def test_page_files():
    print("页面文件：")
    root = Path(__file__).parent
    page = root / "pages" / "studio"
    html = (page / "index.html").read_text(encoding="utf-8")
    css = (page / "style.css").read_text(encoding="utf-8")
    js = (page / "app.js").read_text(encoding="utf-8")
    i18n = root / ".astrbot-plugin" / "i18n" / "zh-CN.json"
    check((page / "index.html").is_file(), "存在 pages/studio/index.html")
    check((page / "app.js").is_file(), "存在外部 module 脚本")
    check("./style.css" in html and "./app.js" in html, "页面使用相对资源路径")
    check("AstrBotPluginPage" in js, "脚本走官方 bridge")
    check('apiPost("generate"' in js, "出图走 generate 接口")
    check('[data-theme="dark"]' in css or '[data-theme="light"]' in css, "样式支持 Dashboard 主题")
    check("绘台" in html, "页面标题为绘台")
    check("proof-image" in html, "成图区不再套裁切框")
    check(i18n.is_file(), "存在插件页中文 i18n")


def main():
    print("=" * 56)
    print("NAI 绘台 WebUI 测试")
    print("=" * 56)
    for func in (
        test_route_registration,
        test_bootstrap_and_gallery,
        test_generate_success_and_validation,
        test_path_guard_and_covers,
        test_stego_and_extract,
        test_page_files,
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
