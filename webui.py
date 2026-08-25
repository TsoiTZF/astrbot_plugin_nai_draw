"""暗房 WebUI：AstrBot Plugin Pages 后端。

聊天出图与页面出图共用 `_produce_image`，不另开第二套生成链路。
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
import uuid
from pathlib import Path

from astrbot.api import logger

from .nai_api import NaiAPIError
from .composition_presets import composition_scene, composition_scene_payload
from .presets import (
    PRESET_ORDER,
    PRESETS,
    preset_number,
    resolve_preset,
    resolve_size,
    sanitize_artist_string,
    variant_count,
)
from .translator import to_tags
from .vangonography_api import (
    StegoFormatError,
    StegoIntegrityError,
    StegoPasswordError,
    extract_file_from_image,
    hide_file_into_image,
)

try:
    from astrbot.api.web import (
        error_response,
        file_response,
        json_response,
        request,
    )
except ImportError:  # 旧版 AstrBot 或离线测试桩
    request = None

    def json_response(data=None, *, status_code=200, headers=None):
        return {} if data is None else data

    def error_response(message, *, status_code=400, data=None, headers=None):
        return {"status": "error", "message": message, "data": data}

    def file_response(path, *, filename=None, content_type=None, headers=None):
        return {
            "path": str(path),
            "filename": filename,
            "content_type": content_type,
        }


PLUGIN_ROUTE_NAMES = ("nai_draw", "astrbot_plugin_nai_draw")
WEBUI_SENDER_PREFIX = "webui:"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
COVER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
SIZE_CHOICES = (
    {"key": "832x1216", "label": "竖图", "hint": "832×1216"},
    {"key": "832x832", "label": "方图", "hint": "832×832"},
    {"key": "1216x832", "label": "横图", "hint": "1216×832"},
    {"key": "1024x1024", "label": "大图", "hint": "1024×1024"},
)


class WebUIError(Exception):
    """页面可展示的业务错误。"""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def register_webui(plugin):
    """把暗房 API 挂到插件实例；无 Dashboard 时静默跳过注册。"""
    ui = NaiWebUI(plugin)
    plugin._webui = ui
    context = getattr(plugin, "context", None)
    register = getattr(context, "register_web_api", None)
    if not callable(register):
        logger.info("[叶子的逼] 当前环境没有 register_web_api，跳过暗房路由")
        return ui

    routes = (
        ("bootstrap", ui.bootstrap, ["GET"], "暗房启动数据"),
        ("generate", ui.generate, ["POST"], "暗房出图"),
        ("gallery", ui.gallery, ["GET"], "暗房样张列表"),
        ("preview", ui.preview, ["GET"], "暗房图片预览"),
        ("download", ui.download, ["GET"], "暗房图片下载"),
        ("covers", ui.covers, ["GET"], "暗房载体列表"),
        ("covers/upload", ui.upload_cover, ["POST"], "暗房上传载体"),
        ("covers/delete", ui.delete_cover, ["POST"], "暗房删除载体"),
        ("extract/prepare", ui.prepare_extract, ["POST"], "暗房提取密码"),
        ("extract", ui.extract, ["POST"], "暗房提取隐写"),
    )
    for prefix in PLUGIN_ROUTE_NAMES:
        for path, handler, methods, desc in routes:
            register(f"/{prefix}/{path}", handler, methods, desc)
    logger.info("[叶子的逼] 暗房 WebUI 路由已注册")
    return ui


class NaiWebUI:
    """Dashboard 插件页使用的出图与图库接口。"""

    def __init__(self, plugin):
        self.plugin = plugin
        self._extract_password = {}

    def _respond(self, data):
        return json_response(data)

    def _fail(self, message, status_code=400):
        return error_response(str(message), status_code=status_code)

    def _sender_id(self):
        username = "dashboard"
        if request is not None:
            try:
                username = str(request.username or "dashboard")
            except RuntimeError:
                username = "dashboard"
        return f"{WEBUI_SENDER_PREFIX}{username}"

    def _query(self, key, default=""):
        if request is None:
            return default
        try:
            value = request.query.get(key, default)
        except RuntimeError:
            return default
        return default if value is None else value

    async def _read_json(self, payload=None):
        if isinstance(payload, dict):
            return payload
        if request is None:
            return {}
        try:
            data = await request.json(default={})
        except RuntimeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def _read_upload(self, payload=None):
        if payload is not None and getattr(payload, "filename", None):
            return payload
        if request is None:
            return None
        try:
            files = await request.files()
        except RuntimeError:
            return None
        upload = files.get("file") if files is not None else None
        if upload is None or not getattr(upload, "filename", None):
            return None
        return upload

    def _safe_filename(self, name):
        raw = Path(str(name or "").replace("\\", "/")).name.strip()
        if not raw or raw in {".", ".."}:
            return None
        if any(char in INVALID_FILENAME_CHARS or ord(char) < 32 for char in raw):
            return None
        suffix = Path(raw).suffix.lower()
        if suffix not in COVER_SUFFIXES:
            return None
        if len(raw) > 120:
            return None
        return raw

    def _resolve_in(self, directory, name):
        safe = self._safe_filename(name)
        if not safe:
            return None
        root = Path(directory).resolve()
        path = (root / safe).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path

    def _locate_image(self, name):
        safe = self._safe_filename(name)
        if not safe:
            return None
        for directory in (
            self.plugin._out_dir,
            self.plugin._steg_dir,
            self.plugin._cover_dir,
        ):
            path = self._resolve_in(directory, safe)
            if path is not None and path.is_file():
                return path
        return None

    def _stat_item(self, path, kind):
        stat = path.stat()
        preset = ""
        if kind == "output":
            parts = path.stem.split("_")
            if len(parts) >= 3 and parts[0] == "nai":
                preset = parts[1]
        return {
            "name": path.name,
            "kind": kind,
            "preset": preset,
            "size": int(stat.st_size),
            "mtime": int(stat.st_mtime),
        }

    def _list_outputs(self, limit=24):
        files = sorted(
            self.plugin._out_dir.glob("nai_*.png"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return [self._stat_item(path, "output") for path in files[:limit]]

    def _list_covers(self):
        files = [
            path
            for path in self.plugin._cover_dir.iterdir()
            if path.is_file() and path.suffix.lower() in COVER_SUFFIXES
        ]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return [self._stat_item(path, "cover") for path in files]

    def _preset_payload(self):
        items = [
            {
                "number": 0,
                "key": "none",
                "label": PRESETS["none"]["label"],
                "faces": 0,
            }
        ]
        for index, key in enumerate(PRESET_ORDER, start=1):
            items.append(
                {
                    "number": index,
                    "key": key,
                    "label": PRESETS[key]["label"],
                    "faces": variant_count(key),
                    "source": dict(PRESETS[key].get("source") or {}),
                }
            )
        return items

    def _encode_image(self, path):
        data = Path(path).read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        return {
            "name": Path(path).name,
            "mime": mime,
            "data": base64.b64encode(data).decode("ascii"),
        }

    async def bootstrap(self, payload=None):
        """返回页面首屏所需的预设、尺寸、样张和载体。"""
        plugin = self.plugin
        try:
            return self._respond(
                {
                    "configured": bool(plugin._api.configured),
                    "model": plugin._api._model,
                    "default_preset": plugin._default_preset(),
                    "default_size": plugin._default_size(),
                    "allow_nsfw": plugin._bool_config("allow_nsfw", False),
                    "enable_face_variation": plugin._bool_config(
                        "enable_face_variation", True
                    ),
                    "llm_translate": plugin._use_llm_translate(),
                    "max_concurrent": plugin._max_concurrent(),
                    "cover_dir": str(plugin._cover_dir),
                    "presets": self._preset_payload(),
                    "composition_scenes": composition_scene_payload(),
                    "sizes": list(SIZE_CHOICES),
                    "gallery": self._list_outputs(),
                    "covers": self._list_covers(),
                }
            )
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房启动失败: {exc}", exc_info=True)
            return self._fail("暗房启动失败，请查看插件日志。", 500)

    async def gallery(self, payload=None):
        return self._respond({"gallery": self._list_outputs()})

    async def covers(self, payload=None):
        return self._respond(
            {
                "cover_dir": str(self.plugin._cover_dir),
                "covers": self._list_covers(),
            }
        )

    async def preview(self, payload=None):
        name = (payload or {}).get("name") if isinstance(payload, dict) else None
        name = name or self._query("name")
        path = self._locate_image(name)
        if path is None:
            return self._fail("找不到这张图片。")
        try:
            return self._respond({"image": self._encode_image(path)})
        except OSError as exc:
            logger.error(f"[叶子的逼] 暗房预览失败: {exc}", exc_info=True)
            return self._fail("图片读取失败。", 500)

    async def download(self, payload=None):
        name = (payload or {}).get("name") if isinstance(payload, dict) else None
        name = name or self._query("name")
        path = self._locate_image(name)
        if path is None:
            return self._fail("找不到这张图片。")
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        return file_response(path, filename=path.name, content_type=mime)

    async def generate(self, payload=None):
        try:
            data = await self._do_generate(await self._read_json(payload))
            return self._respond(data)
        except WebUIError as exc:
            return self._fail(str(exc), exc.status_code)
        except NaiAPIError as exc:
            return self._fail(str(exc), 502)
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房出图失败: {exc}", exc_info=True)
            return self._fail(f"内部错误：{type(exc).__name__}", 500)

    async def _do_generate(self, data):
        plugin = self.plugin
        if not plugin._api.configured:
            raise WebUIError("插件未配置 API 地址或密钥，请先在管理面板填写。")

        prompt_text = str(data.get("prompt") or "").strip()
        scene = None
        if data.get("random_scene"):
            scene = composition_scene(data.get("scene_index"))
            prompt_text = scene["prompt"]
        if not prompt_text:
            raise WebUIError("请填写画面描述。")

        preset_key = resolve_preset(data.get("preset") or plugin._default_preset())
        if not preset_key:
            raise WebUIError(f"未知预设，请从 0～{len(PRESET_ORDER)} 中选择。")
        requested_size = str(data.get("size") or plugin._default_size())
        size = resolve_size(requested_size, "")
        if not size:
            size = plugin._default_size()
            size_note = f"尺寸 {requested_size} 不可用，已用 {size}"
        else:
            size_note = ""

        sender_id = self._sender_id()
        if "nsfw" in data:
            plugin._user_nsfw[sender_id] = bool(data.get("nsfw"))
        if "face_variation" in data:
            plugin._user_face_variation[sender_id] = bool(data.get("face_variation"))

        artist_text = str(data.get("artists") or "").strip()
        rejected = 0
        if artist_text:
            tags, rejected = sanitize_artist_string(artist_text)
            if not tags:
                raise WebUIError(
                    "没有合法画师标签。请使用 artist:名称，或填写单个英文画师名。"
                )
            plugin._user_artists[sender_id] = tags
        else:
            plugin._user_artists.pop(sender_id, None)

        if data.get("stego"):
            plugin._steg_enabled[sender_id] = True
            password = str(data.get("stego_password") or "").strip() or None
            if password:
                plugin._steg_password[sender_id] = password
            else:
                plugin._steg_password.pop(sender_id, None)
        else:
            plugin._steg_enabled.pop(sender_id, None)
            plugin._steg_password.pop(sender_id, None)

        try:
            description, note = await to_tags(
                plugin.context, prompt_text, plugin._use_llm_translate()
            )
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房描述转换异常: {exc}", exc_info=True)
            raise WebUIError("描述转换失败，请稍后重试。") from exc

        warning = "；".join(part for part in (size_note, note) if part)
        if not str(description or "").strip():
            raise WebUIError(warning or "没有可用于绘图的英文标签。")

        produced = await plugin._produce_image(
            description,
            preset_key,
            size,
            sender_id,
            warning=warning,
        )
        image_path = Path(produced["path"])
        stego = None
        if plugin._steg_enabled.get(sender_id, False):
            stego = await self._embed_stego(image_path, sender_id, preset_key)

        return {
            "name": image_path.name,
            "preset": preset_key,
            "preset_number": preset_number(preset_key),
            "preset_label": PRESETS[preset_key]["label"],
            "size": size,
            "nsfw": plugin._allow_nsfw(sender_id),
            "face_variation": plugin._face_variation_enabled(sender_id),
            "artists": list(plugin._artist_tags(sender_id)),
            "rejected_artists": rejected,
            "note": warning,
            "scene": scene,
            "prompt": produced["prompt"],
            "negative": produced["negative"],
            "image": self._encode_image(image_path),
            "stego": stego,
            "gallery": self._list_outputs(),
        }

    async def _embed_stego(self, generated_path, sender_id, preset_key):
        plugin = self.plugin
        try:
            cover_path = plugin._pick_random_cover()
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        session_id = uuid.uuid4().hex[:8]
        output_path = plugin._steg_dir / f"{session_id}_stego.png"
        password = plugin._steg_password.get(str(sender_id))
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: hide_file_into_image(
                    cover_path=cover_path,
                    file_path=generated_path,
                    file_name=Path(generated_path).name,
                    output_path=output_path,
                    encrypt=bool(password),
                    password=password,
                ),
            )
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房隐写失败: {exc}", exc_info=True)
            return {"ok": False, "message": f"隐写失败：{exc}"}

        plugin._last_stego[str(sender_id)] = str(output_path.resolve())
        if not plugin._bool_config("keep_images", False):
            plugin._prune_stego(keep=20)
        logger.info(
            f"[叶子的逼] 暗房隐写完成 sender={sender_id} preset={preset_key} "
            f"cover={cover_path.name}"
        )
        return {
            "ok": True,
            "name": output_path.name,
            "cover_name": cover_path.name,
            "encrypted": bool(password),
        }

    async def upload_cover(self, payload=None):
        try:
            upload = await self._read_upload(payload)
            if upload is None:
                raise WebUIError("请选择要加入载体图库的图片。")
            saved = await self._save_cover(upload)
            return self._respond(
                {
                    "name": saved.name,
                    "covers": self._list_covers(),
                }
            )
        except WebUIError as exc:
            return self._fail(str(exc), exc.status_code)
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房载体上传失败: {exc}", exc_info=True)
            return self._fail(f"载体图保存失败：{exc}", 500)

    async def _save_cover(self, upload):
        filename = self._safe_filename(getattr(upload, "filename", "") or "")
        if filename is None:
            filename = f"cover_{time.time_ns()}.png"
        if Path(filename).suffix.lower() not in COVER_SUFFIXES:
            filename = f"{Path(filename).stem}.png"
        target = self._resolve_in(self.plugin._cover_dir, filename)
        if target is None:
            raise WebUIError("文件名无效。")
        if target.exists():
            target = self.plugin._cover_dir / f"cover_{time.time_ns()}{target.suffix}"

        if hasattr(upload, "save"):
            await upload.save(target)
        else:
            data = await upload.read()
            target.write_bytes(data)

        size = target.stat().st_size if target.is_file() else 0
        if size <= 0:
            try:
                target.unlink()
            except OSError:
                pass
            raise WebUIError("上传的图片是空文件。")
        if size > MAX_UPLOAD_BYTES:
            try:
                target.unlink()
            except OSError:
                pass
            raise WebUIError("图片超过 12MB，请换一张更小的载体。")
        return target

    async def delete_cover(self, payload=None):
        data = await self._read_json(payload)
        path = self._resolve_in(self.plugin._cover_dir, data.get("name"))
        if path is None or not path.is_file():
            return self._fail("找不到这张载体图。")
        try:
            path.unlink()
        except OSError as exc:
            return self._fail(f"删除失败：{exc}", 500)
        return self._respond({"deleted": path.name, "covers": self._list_covers()})

    async def prepare_extract(self, payload=None):
        data = await self._read_json(payload)
        password = str(data.get("password") or "").strip() or None
        sender_id = self._sender_id()
        if password:
            self._extract_password[sender_id] = password
        else:
            self._extract_password.pop(sender_id, None)
        return self._respond({"ready": True, "has_password": bool(password)})

    async def extract(self, payload=None):
        try:
            upload = await self._read_upload(payload)
            password = None
            if isinstance(payload, dict):
                password = payload.get("password")
                if upload is None:
                    upload = payload.get("file")
            if upload is None:
                raise WebUIError("请上传机器人发出的原始隐写 PNG。")
            if request is not None and password is None:
                try:
                    form = await request.form()
                    password = form.get("password")
                except Exception:
                    password = self._query("password") or None
            password = str(password or "").strip() or None
            if password is None:
                password = self._extract_password.pop(self._sender_id(), None)
            image = await self._extract_upload(upload, password)
            return self._respond({"image": image})
        except WebUIError as exc:
            return self._fail(str(exc), exc.status_code)
        except (StegoFormatError, StegoIntegrityError, StegoPasswordError) as exc:
            return self._fail(str(exc))
        except Exception as exc:
            logger.error(f"[叶子的逼] 暗房提取失败: {exc}", exc_info=True)
            return self._fail(f"提取失败：{exc}", 500)

    async def _extract_upload(self, upload, password):
        session_id = uuid.uuid4().hex[:8]
        received = self.plugin._steg_dir / f"{session_id}_received.png"
        extract_dir = self.plugin._steg_dir / f"{session_id}_extract"
        result_path = None
        try:
            if hasattr(upload, "save"):
                await upload.save(received)
            else:
                received.write_bytes(await upload.read())
            if received.stat().st_size > MAX_UPLOAD_BYTES:
                raise WebUIError("图片超过 12MB，请只上传原始 PNG 文件。")
            loop = asyncio.get_running_loop()
            result_path = await loop.run_in_executor(
                None,
                lambda: extract_file_from_image(
                    image_path=received,
                    output_dir=extract_dir,
                    password=password,
                ),
            )
            return self._encode_image(result_path)
        finally:
            for path in (result_path, received):
                try:
                    if path and Path(path).exists():
                        Path(path).unlink()
                except OSError:
                    pass
            try:
                if extract_dir.exists():
                    extract_dir.rmdir()
            except OSError:
                pass
