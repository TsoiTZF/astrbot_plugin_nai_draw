"""AstrBot 叶子的逼插件 v1.8.1

基于 NovelAI Diffusion 4.5，内置实测可用的画师串预设。
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
import asyncio
import base64
import inspect
import math
import random
import re
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from .nai_api import NaiAPI, NaiAPIError
from .composition_presets import composition_scene
from .translator import to_tags
from .vangonography_api import (
    StegoFormatError,
    StegoIntegrityError,
    StegoPasswordError,
    extract_file_from_image,
    hide_file_into_image,
)
from .presets import (
    MAX_CUSTOM_ARTISTS,
    PRESET_ORDER,
    PRESETS,
    build_negative,
    build_prompt,
    preset_help,
    preset_number,
    random_artist_combo,
    resolve_preset,
    resolve_size,
    sanitize_artist_string,
    variant_count,
)
from .webui import register_webui

# 参数前缀：用户可用 -风格 / -尺寸 指定，其余文本作为画面描述
ARG_PATTERN = re.compile(r"-(?:风格|预设|style|p)\s*[=:]?\s*(\S+)", re.I)
SIZE_PATTERN = re.compile(r"-(?:尺寸|size|s)\s*[=:]?\s*(\S+)", re.I)
QUICK_PRESET_PATTERN = re.compile(r"^\s*(\d+)(?:\s+|$)")

@register("nai_draw", "TsoiTZF", "叶子的逼，NovelAI 绘画与画师串预设，支持图片隐写", "1.8.1")
class NaiDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self._api = self._build_api()
        self._semaphore = asyncio.Semaphore(self._max_concurrent())
        self._last_call = {}
        self._user_presets = {}
        self._user_nsfw = {}
        self._user_face_variation = {}
        self._user_artists = {}
        self._variant_positions = {}
        self._last_image = {}
        self._steg_enabled = {}
        self._steg_password = {}
        self._last_stego = {}
        self._data_dir = StarTools.get_data_dir("astrbot_plugin_nai_draw")
        self._steg_dir = self._data_dir / "stego"
        self._steg_dir.mkdir(parents=True, exist_ok=True)
        self._cover_dir = self._resolve_cover_dir()
        self._cover_dir.mkdir(parents=True, exist_ok=True)
        self._out_dir = self._data_dir / "output"
        self._out_dir.mkdir(parents=True, exist_ok=True)
        register_webui(self)

    def _resolve_cover_dir(self):
        """解析载体图库目录，配置优先，留空时用插件数据目录下的 covers。"""
        raw = str(self.config.get("cover_dir", "") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return self._data_dir / "covers"

    async def initialize(self):
        if not self._api.configured:
            logger.warning("[叶子的逼] 未配置 API 地址或密钥，指令将无法使用")
        else:
            logger.info(f"[叶子的逼] 已就绪，默认预设: {self._default_preset()}")
        if getattr(self, "_webui", None):
            logger.info("[叶子的逼] 暗房 WebUI 已注册")

    # ==================== 配置读取 ====================

    def _build_api(self):
        model = str(
            self.config.get("model", "nai-diffusion-4-5-full")
            or "nai-diffusion-4-5-full"
        ).strip()
        return NaiAPI(
            self.config.get("api_base", ""),
            self.config.get("api_key", ""),
            model,
            self._int_config("timeout", 180, 1, 600),
            self._float_config("retry_backoff", 1.0, 0.0, 8.0),
        )

    def _int_config(self, key, fallback, minimum=None, maximum=None):
        """读取整数配置并限制范围，避免非法配置导致运行时崩溃。"""
        try:
            value = int(self.config.get(key, fallback))
        except (TypeError, ValueError):
            logger.warning(f"[叶子的逼] 配置 {key} 非法，已回退 {fallback}")
            value = fallback
        if minimum is not None and value < minimum:
            logger.warning(f"[叶子的逼] 配置 {key} 过小，已调整为 {minimum}")
            value = minimum
        if maximum is not None and value > maximum:
            logger.warning(f"[叶子的逼] 配置 {key} 过大，已调整为 {maximum}")
            value = maximum
        return value

    def _float_config(self, key, fallback, minimum=None, maximum=None):
        """读取浮点配置并限制范围。"""
        try:
            value = float(self.config.get(key, fallback))
        except (TypeError, ValueError):
            logger.warning(f"[叶子的逼] 配置 {key} 非法，已回退 {fallback}")
            value = fallback
        if not math.isfinite(value):
            logger.warning(f"[叶子的逼] 配置 {key} 非法，已回退 {fallback}")
            value = fallback
        if minimum is not None and value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        return value

    def _bool_config(self, key, fallback=False):
        """兼容管理面板布尔值和字符串布尔值。"""
        value = self.config.get(key, fallback)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "是", "开启", "允许"}:
            return True
        if normalized in {"0", "false", "no", "off", "否", "关闭", "禁止"}:
            return False
        logger.warning(f"[叶子的逼] 配置 {key} 不是有效布尔值，已回退 {fallback}")
        return fallback

    def _max_concurrent(self):
        return self._int_config("max_concurrent", 2, 1, 16)

    def _cooldown(self):
        return self._int_config("cooldown", 15, 0, 86400)

    def _retries(self):
        return self._int_config("retries", 3, 1, 5)

    def _default_preset(self):
        """读取默认预设，未知或已废弃值回退冰蓝柔光。"""
        key = resolve_preset(self.config.get("default_preset", "iceblue"))
        return key or "iceblue"

    def _default_size(self):
        return resolve_size(self.config.get("default_size", "832x1216"))

    def _use_llm_translate(self):
        """是否允许词典未命中时调用 LLM 补翻译。"""
        return self._bool_config("llm_translate", True)

    def _allow_nsfw(self, sender_id=None):
        """返回用户个人设置；未设置时继承管理面板默认值。"""
        key = str(sender_id) if sender_id is not None else None
        if key is not None and key in self._user_nsfw:
            return self._user_nsfw[key]
        return self._bool_config("allow_nsfw", False)

    def _face_variation_enabled(self, sender_id=None):
        """返回自动脸型个人设置；未设置时继承管理面板默认值。"""
        key = str(sender_id) if sender_id is not None else None
        if key is not None and key in self._user_face_variation:
            return self._user_face_variation[key]
        return self._bool_config("enable_face_variation", True)

    def _artist_tags(self, sender_id=None):
        """返回当前用户按添加顺序保存的个人画师标签。"""
        key = str(sender_id) if sender_id is not None else None
        return self._user_artists.get(key, ()) if key is not None else ()

    def _artist_string(self, sender_id=None):
        """返回可直接合并进正面提示词的个人画师串。"""
        return ", ".join(self._artist_tags(sender_id))

    def _sender_id(self, event):
        """将事件发送者统一为可作为字典键的字符串。"""
        try:
            value = event.get_sender_id()
        except Exception:
            value = "unknown"
        return str(value or "unknown")

    # ==================== 指令 ====================

    @filter.command("nai预设")
    async def cmd_presets(self, event: AstrMessageEvent):
        """列出可用画风预设与尺寸写法。"""
        text = preset_help()
        sender_id = self._sender_id(event)
        selected = self._user_presets.get(sender_id)
        if selected:
            number = preset_number(selected)
            text += (
                f"\n\n你的选择：{number} = {PRESETS[selected]['label']} [{selected}]"
            )
        else:
            default = self._default_preset()
            number = preset_number(default)
            text += f"\n\n当前默认：{number} = {PRESETS[default]['label']} [{default}]"
        text += f"\n默认尺寸：{self._default_size()}"
        text += (
            "\n\n无预设：/nai 0 或 /nai 0 长发女孩"
            "\n选择预设：/nai 1"
            "\n选择并绘图：/nai 1 长发女孩"
            "\n个人画师：/nai画师 添加 artist:名称"
            "\n随机画师串：/nai画师 随机"
            "\n随机完整场景：/nai随机 -风格 1 -尺寸 横图"
        )
        return event.plain_result(text)

    @filter.command("nainsfw")
    async def cmd_nsfw(self, event: AstrMessageEvent, args: str = ""):
        """查看或修改当前用户的 NSFW 模式。"""
        sender_id = self._sender_id(event)
        action = str(args or "").strip().lower()

        if action in {"开", "开启", "on", "1"}:
            self._user_nsfw[sender_id] = True
            return event.plain_result("[成功] NSFW 已开启，仅对你生效。")
        if action in {"关", "关闭", "off", "0"}:
            self._user_nsfw[sender_id] = False
            return event.plain_result("[成功] NSFW 已关闭，仅对你生效。")
        if action in {"默认", "重置", "reset"}:
            self._user_nsfw.pop(sender_id, None)
            state = "开启" if self._allow_nsfw(sender_id) else "关闭"
            return event.plain_result(f"[成功] 已恢复管理面板默认值：{state}。")
        if action in {"", "状态", "status"}:
            state = "开启" if self._allow_nsfw(sender_id) else "关闭"
            source = "个人设置" if sender_id in self._user_nsfw else "管理面板默认"
            return event.plain_result(
                f"当前 NSFW：{state}（{source}）\n"
                "用法：/nainsfw 开 | 关 | 状态 | 默认"
            )
        return event.plain_result("用法：/nainsfw 开 | 关 | 状态 | 默认")

    @filter.command("nai脸型")
    async def cmd_face_variation(self, event: AstrMessageEvent, args: str = ""):
        """查看或修改当前用户的自动脸型模式。"""
        sender_id = self._sender_id(event)
        action = str(args or "").strip().lower()

        if action in {"开", "开启", "on", "1"}:
            self._user_face_variation[sender_id] = True
            return event.plain_result("[成功] 自动脸型已开启，仅对你生效。")
        if action in {"关", "关闭", "off", "0"}:
            self._user_face_variation[sender_id] = False
            return event.plain_result(
                "[成功] 自动脸型已关闭，仅对你生效；画师轮换保持开启。"
            )
        if action in {"默认", "重置", "reset"}:
            self._user_face_variation.pop(sender_id, None)
            state = "开启" if self._face_variation_enabled(sender_id) else "关闭"
            return event.plain_result(f"[成功] 已恢复管理面板默认值：{state}。")
        if action in {"", "状态", "status"}:
            state = "开启" if self._face_variation_enabled(sender_id) else "关闭"
            source = (
                "个人设置"
                if sender_id in self._user_face_variation
                else "管理面板默认"
            )
            return event.plain_result(
                f"当前自动脸型：{state}（{source}）\n"
                "用法：/nai脸型 开 | 关 | 状态 | 默认"
            )
        return event.plain_result("用法：/nai脸型 开 | 关 | 状态 | 默认")

    @filter.command("nai画师")
    async def cmd_artists(self, event: AstrMessageEvent, args: str = ""):
        """查看或修改当前用户的个人画师串。"""
        sender_id = self._sender_id(event)
        raw = str(args or "").strip()
        action = raw.lower()
        usage = (
            "用法：/nai画师 添加 <画师串> | 设置 <画师串> | "
            "随机 | 删除 <编号> | 状态 | 清空"
        )

        if action in {"", "状态", "查看", "status"}:
            tags = self._artist_tags(sender_id)
            if not tags:
                return event.plain_result(f"当前未设置个人画师串。\n{usage}")
            lines = [f"当前个人画师串（{len(tags)} 个）："]
            lines.extend(f"{index}. {tag}" for index, tag in enumerate(tags, 1))
            lines.append(usage)
            return event.plain_result("\n".join(lines))

        if action in {"清空", "清除", "reset", "clear"}:
            self._user_artists.pop(sender_id, None)
            return event.plain_result("[成功] 已清空你的个人画师串。")

        if action in {"随机", "random"}:
            combo = random_artist_combo()
            self._user_artists[sender_id] = combo["artists"]
            preview = combo["text"]
            if len(preview) > 180:
                preview = preview[:177] + "..."
            return event.plain_result(
                "[成功] 已从实测画师配方中抽取一组并设为个人画师串。\n"
                f"来源：{combo['label']} [{combo['preset']}]\n"
                f"画师串：{preview}"
            )

        head, separator, payload = raw.partition(" ")
        command = head.lower()
        if command in {"删除", "移除", "delete", "remove"}:
            if not separator or not payload.strip().isdecimal():
                return event.plain_result(f"[失败] 请填写要删除的编号。\n{usage}")
            tags = list(self._artist_tags(sender_id))
            index = int(payload.strip()) - 1
            if not 0 <= index < len(tags):
                return event.plain_result(
                    f"[失败] 画师编号范围是 1~{len(tags)}，请发送 /nai画师 状态 查看。"
                    if tags
                    else "[失败] 当前没有可删除的个人画师串。"
                )
            removed = tags.pop(index)
            if tags:
                self._user_artists[sender_id] = tuple(tags)
            else:
                self._user_artists.pop(sender_id, None)
            return event.plain_result(f"[成功] 已删除：{removed}")

        replace = command in {"设置", "替换", "set", "replace"}
        append = command in {"添加", "增加", "add", "append"}
        if replace or append:
            if not separator or not payload.strip():
                return event.plain_result(f"[失败] 缺少画师串。\n{usage}")
            artist_text = payload
        else:
            append = True
            artist_text = raw

        new_tags, rejected = sanitize_artist_string(artist_text)
        if not new_tags:
            return event.plain_result(
                "[失败] 没有合法画师标签。请使用 artist:名称，"
                "或直接填写单个英文画师名；数值权重不得超过 1.5。"
            )

        if append:
            current = self._artist_tags(sender_id)
            combined, overflow = sanitize_artist_string(
                ", ".join((*current, *new_tags)),
                max_tags=MAX_CUSTOM_ARTISTS,
            )
            rejected += overflow
        else:
            combined = new_tags
        self._user_artists[sender_id] = combined

        note = f"；忽略 {rejected} 个无效或超量标签" if rejected else ""
        verb = "设置" if replace else "添加"
        return event.plain_result(
            f"[成功] 已{verb}个人画师串，当前共 {len(combined)} 个{note}。"
        )

    @filter.command("nai随机", alias={"nai_random", "nairandom"})
    async def cmd_random_draw(self, event: AstrMessageEvent, args: str = ""):
        """从构图风格法典随机选取完整场景并生成图片。"""
        if not self._api.configured:
            yield event.plain_result(
                "[失败] 插件未配置 API 地址或密钥，请在管理面板填写后重试。"
            )
            return

        sender_id = self._sender_id(event)
        raw = str(args or "").strip()
        remaining, preset_key, size, warning = self._parse_args(
            raw, self._user_presets.get(sender_id)
        )
        if remaining:
            warning = "；".join(
                part for part in (warning, f"未识别的随机参数已忽略：{remaining}") if part
            )

        blocked = self._cooldown_remaining(sender_id)
        if blocked > 0:
            yield event.plain_result(f"[提示] 冷却中，请 {blocked} 秒后再试。")
            return

        reservation = time.time()
        self._last_call[sender_id] = reservation
        scene = composition_scene()
        yield event.plain_result(
            "[随机] 已从构图风格法典抽取完整场景，正在生成。\n"
            f"场景：{scene['title']}\n"
            f"预设：{preset_number(preset_key)} = {PRESETS[preset_key]['label']}\n"
            f"尺寸：{size}"
        )
        if warning:
            yield event.plain_result(f"[提示] {warning}")

        result = await self._generate_and_send(
            event,
            scene["prompt"],
            preset_key,
            size,
            warning,
            sender_id,
            reservation,
        )
        yield result

    @filter.command("nai")
    async def cmd_draw(self, event: AstrMessageEvent, args: str = ""):
        """生成图片。支持 -风格 与 -尺寸 参数，其余文本为画面描述。"""
        if not self._api.configured:
            yield event.plain_result(
                "[失败] 插件未配置 API 地址或密钥，请在管理面板填写后重试。"
            )
            return

        raw = str(args or "").strip()
        if not raw:
            yield event.plain_result(
                "请描述要画的内容。例如：\n"
                "  /nai 1（选择第一个预设）\n"
                "  /nai 1girl, long hair, white dress\n"
                "  /nai 2 -尺寸 方图 red qipao\n"
                "随机完整场景：/nai随机 [-风格 1] [-尺寸 横图]\n"
                "查看预设：/nai预设\n"
                "无预设：/nai 0 画面描述\n"
                "个人画师：/nai画师 添加 artist:名称\n"
                "随机画师串：/nai画师 随机\n"
                "自动脸型：/nai脸型 关 | 开 | 状态 | 默认\n"
                "隐写模式：/nai隐写 状态"
            )
            return

        sender_id = self._sender_id(event)
        if raw.isdecimal():
            selected = resolve_preset(raw)
            if not selected:
                yield event.plain_result(
                    f"[失败] 预设编号范围是 0~{len(PRESET_ORDER)}，请发送 /nai预设 查看。"
                )
                return
            self._user_presets[sender_id] = selected
            yield event.plain_result(
                f"[成功] 已选择 {raw} = {PRESETS[selected]['label']}。\n"
                "现在发送 /nai 画面描述即可绘图。"
            )
            return

        quick_match = QUICK_PRESET_PATTERN.match(raw)
        if quick_match:
            selected = resolve_preset(quick_match.group(1))
            if not selected:
                yield event.plain_result(
                    f"[失败] 预设编号范围是 0~{len(PRESET_ORDER)}，请发送 /nai预设 查看。"
                )
                return
            self._user_presets[sender_id] = selected

        remaining, preset_key, size, warning = self._parse_args(
            raw, self._user_presets.get(sender_id)
        )
        if not remaining:
            yield event.plain_result("[失败] 只填了参数，缺少画面描述。")
            return

        blocked = self._cooldown_remaining(sender_id)
        if blocked > 0:
            yield event.plain_result(f"[提示] 冷却中，请 {blocked} 秒后再试。")
            return

        # 在第一次 await 前预约冷却，避免同一用户的并发命令同时通过检查。
        reservation = time.time()
        self._last_call[sender_id] = reservation

        current_preset_number = preset_number(preset_key)
        nsfw_state = "开启" if self._allow_nsfw(sender_id) else "关闭"
        face_state = "开启" if self._face_variation_enabled(sender_id) else "关闭"
        artist_count = len(self._artist_tags(sender_id))
        artist_state = f"{artist_count} 个" if artist_count else "未设置"
        yield event.plain_result(
            "[绘图] 指令已生效，正在生成，请稍候。\n"
            f"预设：{current_preset_number} = {PRESETS[preset_key]['label']}\n"
            f"尺寸：{size}\n"
            f"NSFW：{nsfw_state}\n"
            f"自动脸型：{face_state}\n"
            f"个人画师：{artist_state}"
        )

        try:
            # 中文描述需转为 danbooru 标签，NAI 不识别中文。
            description, note = await to_tags(
                self.context, remaining, self._use_llm_translate()
            )
        except Exception as exc:
            self._clear_cooldown(sender_id, reservation)
            logger.error(f"[叶子的逼] 描述转换异常: {exc}", exc_info=True)
            yield event.plain_result("[失败] 描述转换失败，请稍后重试。")
            return
        if note:
            warning = "；".join(part for part in (warning, note) if part)
        if not str(description or "").strip():
            self._clear_cooldown(sender_id, reservation)
            detail = warning or "没有可用于绘图的英文标签"
            yield event.plain_result(f"[失败] {detail}。")
            return
        if warning:
            yield event.plain_result(f"[提示] {warning}")

        yield await self._generate_and_send(
            event, description, preset_key, size, warning, sender_id, reservation
        )

    def _parse_args(self, raw, default_preset=None):
        """拆分参数与描述文本，返回 (描述, 预设, 尺寸, 警告)。"""
        warnings = []

        preset_key = resolve_preset(default_preset) or self._default_preset()
        quick_match = QUICK_PRESET_PATTERN.match(raw)
        if quick_match:
            resolved = resolve_preset(quick_match.group(1))
            if resolved:
                preset_key = resolved
                raw = raw[quick_match.end():]

        match = ARG_PATTERN.search(raw)
        if match:
            resolved = resolve_preset(match.group(1))
            if resolved:
                preset_key = resolved
            else:
                warnings.append(f"未知预设 {match.group(1)}，已用 {preset_key}")
            raw = ARG_PATTERN.sub("", raw, count=1)

        size = self._default_size()
        match = SIZE_PATTERN.search(raw)
        if match:
            resolved = resolve_size(match.group(1), "")
            if not resolved:
                warnings.append(f"尺寸 {match.group(1)} 不可用，已用 {size}")
            else:
                size = resolved
            raw = SIZE_PATTERN.sub("", raw, count=1)

        return raw.strip(" ,，"), preset_key, size, "；".join(warnings)

    def _cooldown_remaining(self, sender_id):
        """返回剩余冷却秒数，0 表示可以执行。"""
        cooldown = self._cooldown()
        if cooldown <= 0:
            return 0
        elapsed = time.time() - self._last_call.get(str(sender_id), 0)
        if elapsed >= cooldown:
            return 0
        return int(cooldown - elapsed) + 1

    def _clear_cooldown(self, sender_id, reservation=None):
        """只清理当前请求预约的冷却，避免覆盖后续请求的状态。"""
        key = str(sender_id)
        if reservation is None or self._last_call.get(key) == reservation:
            self._last_call.pop(key, None)

    def _next_variant_index(self, sender_id, preset_key):
        """按用户和预设推进组合序号，保证一个周期内不重复。"""
        key = (str(sender_id), preset_key)
        count = variant_count(preset_key)
        previous = self._variant_positions.get(key)
        current = (
            random.randrange(count) if previous is None else (previous + 1) % count
        )
        self._variant_positions[key] = current
        return current

    # ==================== 生成与发送 ====================

    async def _generate_and_send(
        self,
        event,
        description,
        preset_key,
        size,
        warning,
        sender_id=None,
        reservation=None,
    ):
        """并发受限地生成图片并发送，失败时回报可读原因。"""
        sender_id = sender_id or self._sender_id(event)
        try:
            produced = await self._produce_image(
                description,
                preset_key,
                size,
                sender_id,
                reservation=reservation,
                warning=warning,
            )
        except NaiAPIError as trans_exc:
            logger.error(f"[叶子的逼] 生成失败: {trans_exc}")
            return event.plain_result(f"[失败] {trans_exc}")
        except (OSError, ValueError, TypeError) as trans_exc:
            logger.error(f"[叶子的逼] 图片保存失败: {trans_exc}", exc_info=True)
            return event.plain_result("[失败] 图片保存失败，请检查插件数据目录。")
        except Exception as trans_exc:
            logger.error(f"[叶子的逼] 未预期异常: {trans_exc}", exc_info=True)
            return event.plain_result(f"[失败] 内部错误：{type(trans_exc).__name__}")

        path = produced["path"]
        # 隐写模式：载体作预览，隐藏数据的 PNG 通过原始文件发送
        if self._steg_enabled.get(str(sender_id), False):
            return await self._hide_into_cover(event, path, sender_id, preset_key)
        return event.image_result(str(path))

    async def _produce_image(
        self,
        description,
        preset_key,
        size,
        sender_id,
        reservation=None,
        warning="",
        generation_params=None,
        extra_negative="",
    ):
        """并发受限地生成并保存图片，聊天与 WebUI 共用此入口。"""
        sender_id = str(sender_id or "unknown")
        if reservation is None:
            reservation = time.time()
            self._last_call[sender_id] = reservation
        # 画师主力与五官逐次轮换，face_negative 用于压制其余变体特征。
        variant_index = self._next_variant_index(sender_id, preset_key)
        face_enabled = self._face_variation_enabled(sender_id)
        prompt, face_negative = build_prompt(
            preset_key,
            description,
            index=variant_index,
            include_face=face_enabled,
            custom_artist=self._artist_string(sender_id),
        )
        negative_extra = ", ".join(
            part
            for part in (
                str(self.config.get("extra_negative", "") or "").strip(),
                str(extra_negative or "").strip(),
            )
            if part
        )
        negative = build_negative(
            preset_key,
            self._allow_nsfw(sender_id),
            negative_extra,
            face_negative,
            description,
            include_face=face_enabled,
        )

        label = PRESETS[preset_key]["label"]
        logger.info(f"[叶子的逼] {sender_id} 请求 {preset_key} {size}")

        async with self._semaphore:
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: self._api.generate(
                        prompt,
                        negative,
                        size,
                        retries=self._retries(),
                        generation_params=generation_params,
                    ),
                )
            except NaiAPIError:
                # 失败不占用冷却，允许立即重试
                self._clear_cooldown(sender_id, reservation)
                raise
            except Exception:
                self._clear_cooldown(sender_id, reservation)
                raise

        try:
            path = self._save_image(data, preset_key)
        except (OSError, ValueError, TypeError):
            self._clear_cooldown(sender_id, reservation)
            raise
        self._last_image[sender_id] = str(path)
        if warning:
            logger.info(f"[叶子的逼] {label} 参数提示: {warning}")
        return {
            "path": path,
            "prompt": prompt,
            "negative": negative,
            "variant_index": variant_index,
            "face_enabled": face_enabled,
            "generation_params": dict(generation_params or {}),
        }

    async def _hide_into_cover(self, event, generated_path, sender_id, preset_key):
        """把生成图隐藏进载体，并把可提取 PNG 作为原始文件发送。"""
        try:
            cover_path = self._pick_random_cover()
        except ValueError as exc:
            logger.warning(f"[叶子的逼] {exc}，本次直接发送原图")
            return self._image_with_notice(
                event,
                f"[提示] {exc}\n本次未执行隐写，已直接发送生成图。",
                generated_path,
            )

        session_id = uuid.uuid4().hex[:8]
        output_path = self._steg_dir / f"{session_id}_stego.png"
        password = self._steg_password.get(str(sender_id))
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: hide_file_into_image(
                    cover_path=cover_path,
                    file_path=generated_path,
                    file_name=generated_path.name,
                    output_path=output_path,
                    encrypt=bool(password),
                    password=password,
                ),
            )
            logger.info(
                f"[叶子的逼] 隐写完成 sender={sender_id} preset={preset_key} "
                f"cover={cover_path.name}"
            )
            self._last_stego[str(sender_id)] = str(output_path.resolve())
            if not self._bool_config("keep_images", False):
                self._prune_stego(keep=20)
            return self._stego_delivery_result(event, cover_path, output_path)
        except Exception as exc:
            logger.error(f"[叶子的逼] 隐写失败，回退发送原图: {exc}", exc_info=True)
            return self._image_with_notice(
                event,
                f"[失败] 隐写失败：{exc}\n已回退发送原始生成图。",
                generated_path,
            )

    @staticmethod
    def _image_with_notice(event, notice, image_path):
        """在同一结果中发送说明和图片。"""
        try:
            from astrbot.api.message_components import Image as CompImage, Plain

            return event.chain_result(
                [Plain(notice), CompImage.fromFileSystem(str(Path(image_path).resolve()))]
            )
        except Exception as exc:
            logger.warning(f"[叶子的逼] 说明消息构造失败，改为只发送图片: {exc}")
            return event.image_result(str(image_path))

    @staticmethod
    def _stego_delivery_result(event, cover_path, output_path):
        """载体仅作预览，隐写图必须走文件消息以避免平台压缩。"""
        from astrbot.api.message_components import (
            File as CompFile,
            Image as CompImage,
            Plain,
        )

        return event.chain_result(
            [
                Plain(
                    "[成功] 隐写完成。\n"
                    "下面第一张是载体预览，不能用于提取；请保存最后的原始 PNG 文件。"
                ),
                CompImage.fromFileSystem(str(Path(cover_path).resolve())),
                Plain("原始隐写文件（提取时请引用或上传这个文件）："),
                CompFile(
                    name=Path(output_path).name,
                    file=str(Path(output_path).resolve()),
                ),
            ]
        )

    def _save_image(self, data, preset_key):
        """写入图片文件，超量时清理旧文件避免磁盘堆积。"""
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("图片数据为空或类型无效")
        name = f"nai_{preset_key}_{time.time_ns()}.png"
        path = self._out_dir / name
        path.write_bytes(data)
        if not self._bool_config("keep_images", False):
            self._prune_output(keep=20)
        return path

    def _prune_output(self, keep=20):
        """只保留最近 keep 个文件，删除失败不影响主流程。"""
        try:
            files = sorted(
                self._out_dir.glob("nai_*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in files[keep:]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError as exc:
            logger.warning(f"[叶子的逼] 清理输出目录失败: {exc}")

    def _prune_stego(self, keep=20):
        """只保留最近的隐写原始文件，当前用户最近一次路径另行记录。"""
        try:
            protected = {
                str(Path(path).resolve())
                for path in self._last_stego.values()
            }
            files = sorted(
                self._steg_dir.glob("*_stego.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in files[keep:]:
                if str(stale.resolve()) in protected:
                    continue
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError as exc:
            logger.warning(f"[叶子的逼] 清理隐写目录失败: {exc}")

    # ==================== 隐写：生图 + 载体图库结合 ====================

    @staticmethod
    async def _find_media_segment(event: AstrMessageEvent):
        """优先查找原始文件，其次查找普通图片，兼容直接消息与引用消息。"""
        try:
            from astrbot.api.message_components import (
                File as CompFile,
                Image as CompImage,
                Reply,
            )
        except ImportError:
            return None, None

        message_obj = getattr(event, "message_obj", None)
        segments = list(getattr(message_obj, "message", None) or [])
        expanded = []
        for segment in segments:
            if isinstance(segment, Reply):
                expanded.extend(list(getattr(segment, "chain", None) or []))
            expanded.append(segment)

        for segment in expanded:
            if not isinstance(segment, CompFile):
                continue
            source = None
            try:
                getter = getattr(segment, "get_file", None)
                source = getter(allow_return_url=True) if getter else None
                if inspect.isawaitable(source):
                    source = await source
            except Exception as exc:
                logger.warning(f"[叶子的逼] 解析消息文件失败: {exc}")
            if not source:
                source = getattr(segment, "file", None) or getattr(
                    segment, "url", None
                )
            if source:
                return str(source), "file"

        for segment in expanded:
            if not isinstance(segment, CompImage):
                continue
            source = (
                getattr(segment, "url", None)
                or getattr(segment, "file", None)
                or getattr(segment, "path", None)
            )
            if source:
                return str(source), "image"
        return None, None

    async def _download_to_bytes(self, source: str) -> bytes:
        """读取 URL、base64 或本地路径，网络读取保持在异步上下文中。"""
        source = str(source)
        if source.startswith("base64://"):
            return base64.b64decode(source[len("base64://"):])
        if source.startswith(("http://", "https://")):
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    source,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    resp.raise_for_status()
                    return await resp.read()

        if source.startswith("file://"):
            parsed = urlparse(source)
            local_path = unquote(parsed.path)
            if parsed.netloc:
                local_path = f"//{parsed.netloc}{local_path}"
            if re.match(r"^/[A-Za-z]:", local_path):
                local_path = local_path[1:]
            path = Path(local_path)
        else:
            path = Path(source)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, path.read_bytes)

    def _pick_random_cover(self) -> Path:
        """从载体图库目录随机取一张图片，返回路径；为空时抛 ValueError。"""
        covers = [
            p for p in self._cover_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
        ]
        if not covers:
            raise ValueError(
                f"载体图库目录为空：{self._cover_dir}\n"
                "请在该目录下放置一些图片作为隐写载体。"
            )
        return random.choice(covers)

    @filter.command("nai隐写", alias={"nai_steg", "naihide"})
    async def cmd_steg_toggle(self, event: AstrMessageEvent, args: str = ""):
        """开启或关闭隐写模式。

        开启后，所有 /nai 生成的图片会自动隐藏进载体图库的随机载体图中，
        同时发送载体预览和不经平台压缩的原始 PNG 文件。
        用 /nai提取 可从原始 PNG 文件还原生成图。

        用法：/nai隐写 开 [密码]   开启隐写，可选密码加密
              /nai隐写 关          关闭隐写，恢复直接发图
              /nai隐写 状态        查看当前隐写状态
        """
        sender_id = self._sender_id(event)
        raw_action = str(args or "").strip()
        parts = raw_action.split(maxsplit=1)
        action = parts[0].lower() if parts else "状态"

        if action in {"关", "关闭", "off", "0"}:
            self._steg_enabled.pop(sender_id, None)
            self._steg_password.pop(sender_id, None)
            return event.plain_result("[成功] 隐写模式已关闭，恢复直接发送生成图。")

        if action in {"开", "开启", "on", "1"}:
            password = parts[1] if len(parts) > 1 else None
            if password and password.lower() in {"不需要", "无", "no", "不加密"}:
                password = None
            self._steg_enabled[sender_id] = True
            if password:
                self._steg_password[sender_id] = password
            else:
                self._steg_password.pop(sender_id, None)
            return event.plain_result(
                "[成功] 隐写模式已开启"
                f"（{'已设置密码' if password else '无加密'}），仅对你生效。\n"
                "生成后请保存机器人发送的原始 PNG 文件，普通图片预览不能用于提取。"
            )

        enabled = self._steg_enabled.get(sender_id, False)
        password = self._steg_password.get(sender_id)
        covers = [p for p in self._cover_dir.iterdir() if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}]
        return event.plain_result(
            f"当前隐写模式：{'开启' if enabled else '关闭'}\n"
            f"加密密码：{'已设置' if password else '无'}\n"
            f"载体图库：{self._cover_dir}（{len(covers)} 张）\n"
            "用法：/nai隐写 开 [密码] | 关 | 状态\n"
            "机器人不会在聊天中回显密码。"
        )

    @filter.command("nai载体", alias={"nai_cover", "naicover"})
    async def cmd_add_cover(self, event: AstrMessageEvent, args: str = ""):
        """将用户上传的图片加入载体图库。

        用法：上传一张图片 + /nai载体 [文件名]
        不填文件名时自动命名。载体图用于隐写时随机选取。
        """
        media_source, _ = await self._find_media_segment(event)
        if not media_source:
            return event.plain_result(
                "请上传或引用一张图片或图片文件后再使用 /nai载体。\n"
                "用法：上传图片/文件 + /nai载体 [文件名]"
            )

        custom_name = str(args or "").strip()
        try:
            img_data = await self._download_to_bytes(media_source)
        except Exception as exc:
            logger.error(f"[叶子的逼] 载体图下载失败: {exc}", exc_info=True)
            return event.plain_result(f"[失败] 图片下载失败：{exc}")

        if custom_name:
            custom_name = Path(custom_name.replace("\\", "/")).name
            if not custom_name or custom_name in {".", ".."}:
                return event.plain_result("[失败] 文件名无效。")
            if not Path(custom_name).suffix:
                custom_name += ".png"
            save_path = self._cover_dir / custom_name
        else:
            save_path = self._cover_dir / f"cover_{time.time_ns()}.png"

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, save_path.write_bytes, img_data)
        except OSError as exc:
            logger.error(f"[叶子的逼] 载体图保存失败: {exc}", exc_info=True)
            return event.plain_result(f"[失败] 载体图保存失败：{exc}")

        covers = [p for p in self._cover_dir.iterdir() if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}]
        return event.plain_result(
            f"[成功] 载体图已加入图库：{save_path.name}\n"
            f"当前载体图库共 {len(covers)} 张。"
        )

    @filter.command("nai提取", alias={"nai_extract", "naiunhide"})
    async def cmd_steg_extract(self, event: AstrMessageEvent, args: str = ""):
        """从原始隐写 PNG 或服务器最近一次记录中提取生成图片。

        用法：引用原始 PNG 文件 + /nai提取 [密码]
              /nai提取 最近 [密码]
        """
        sender_id = self._sender_id(event)
        raw_args = str(args or "").strip()
        parts = raw_args.split(maxsplit=1)
        use_latest = bool(parts and parts[0].lower() in {"最近", "latest"})
        media_kind = None

        if use_latest:
            password = parts[1] if len(parts) > 1 else self._steg_password.get(sender_id)
            image_path = Path(self._last_stego.get(sender_id, ""))
            if not image_path.is_file():
                yield event.plain_result(
                    "[失败] 没有可用的最近隐写原图。\n"
                    "插件重载或旧文件被清理后，请改为上传机器人发送的原始 PNG 文件。"
                )
                return
            media_kind = "server"
            media_source = str(image_path)
        else:
            password = raw_args or None
            media_source, media_kind = await self._find_media_segment(event)
            if not media_source:
                yield event.plain_result(
                    "请上传或引用机器人发送的原始 PNG 文件后再使用 /nai提取。\n"
                    "也可直接使用：/nai提取 最近 [密码]"
                )
                return

        if password and password.lower() in {"不需要", "无", "no", "不加密"}:
            password = None

        yield event.plain_result("收到。正在提取隐藏文件，请稍候...")

        session_id = uuid.uuid4().hex[:8]
        temporary_image = None
        result_path = None
        extract_dir = self._steg_dir / f"{session_id}_extract"
        try:
            loop = asyncio.get_running_loop()
            if media_kind == "server":
                extraction_source = Path(media_source)
            else:
                img_data = await self._download_to_bytes(media_source)
                temporary_image = self._steg_dir / f"{session_id}_received.png"
                await loop.run_in_executor(None, temporary_image.write_bytes, img_data)
                extraction_source = temporary_image

            result_path = await loop.run_in_executor(
                None,
                lambda: extract_file_from_image(
                    image_path=extraction_source,
                    output_dir=extract_dir,
                    password=password,
                ),
            )

            yield event.image_result(str(result_path))
            logger.info(f"[叶子的逼] 提取完成 file={Path(result_path).name}")
        except (StegoFormatError, StegoIntegrityError, StegoPasswordError) as exc:
            message = f"提取失败：{exc}"
            if media_kind == "image" and isinstance(
                exc,
                (StegoFormatError, StegoIntegrityError),
            ):
                message += (
                    "\n[提示] 你引用的是普通图片消息。QQ 会压缩图片并破坏隐写数据，"
                    "请改为引用机器人发送的原始 PNG 文件，或使用 /nai提取 最近。"
                )
            yield event.plain_result(message)
        except Exception as exc:
            logger.error(f"[叶子的逼] 提取失败: {exc}", exc_info=True)
            yield event.plain_result(f"[失败] 提取失败：{exc}")
        finally:
            for path in (result_path, temporary_image):
                try:
                    if path and path.exists():
                        path.unlink()
                except OSError:
                    pass
            try:
                if extract_dir.exists():
                    extract_dir.rmdir()
            except OSError:
                pass

    async def terminate(self):
        self._last_call.clear()
        self._user_presets.clear()
        self._user_nsfw.clear()
        self._user_face_variation.clear()
        self._user_artists.clear()
        self._variant_positions.clear()
        self._last_image.clear()
        self._steg_enabled.clear()
        self._steg_password.clear()
        self._last_stego.clear()
        logger.info("[叶子的逼] 插件已卸载")
