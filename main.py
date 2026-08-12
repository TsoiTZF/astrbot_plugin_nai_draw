"""AstrBot 叶子的逼插件 v1.5.0

基于 NovelAI Diffusion 4.5，内置实测可用的画师串预设。
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
import asyncio
import base64
import math
import random
import re
import time
import uuid
from pathlib import Path

from .nai_api import NaiAPI, NaiAPIError
from .translator import to_tags
from .vangonography_api import hide_file_into_image, extract_file_from_image
from .presets import (
    MAX_CUSTOM_ARTISTS,
    PRESET_ORDER,
    PRESETS,
    build_negative,
    build_prompt,
    preset_help,
    preset_number,
    resolve_preset,
    resolve_size,
    sanitize_artist_string,
    variant_count,
)

# 参数前缀：用户可用 -风格 / -尺寸 指定，其余文本作为画面描述
ARG_PATTERN = re.compile(r"-(?:风格|预设|style|p)\s*[=:]?\s*(\S+)", re.I)
SIZE_PATTERN = re.compile(r"-(?:尺寸|size|s)\s*[=:]?\s*(\S+)", re.I)
QUICK_PRESET_PATTERN = re.compile(r"^\s*(\d+)(?:\s+|$)")

@register("nai_draw", "TsoiTZF", "叶子的逼，NovelAI 绘画与画师串预设，支持图片隐写", "1.6.0")
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
        self._data_dir = StarTools.get_data_dir("astrbot_plugin_nai_draw")
        self._steg_dir = self._data_dir / "stego"
        self._steg_dir.mkdir(parents=True, exist_ok=True)
        self._cover_dir = self._resolve_cover_dir()
        self._cover_dir.mkdir(parents=True, exist_ok=True)
        self._out_dir = self._data_dir / "output"
        self._out_dir.mkdir(parents=True, exist_ok=True)

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
        """读取默认预设，未知值回退 laowuyang。"""
        key = resolve_preset(self.config.get("default_preset", "laowuyang"))
        return key or "laowuyang"

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
            "删除 <编号> | 状态 | 清空"
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
                "查看预设：/nai预设\n"
                "无预设：/nai 0 画面描述\n"
                "个人画师：/nai画师 添加 artist:名称\n"
                "自动脸型：/nai脸型 关 | 开 | 状态 | 默认"
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
        negative = build_negative(
            preset_key,
            self._allow_nsfw(sender_id),
            self.config.get("extra_negative", ""),
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
                        prompt, negative, size, retries=self._retries()
                    ),
                )
            except NaiAPIError as exc:
                # 失败不占用冷却，允许立即重试
                self._clear_cooldown(sender_id, reservation)
                logger.error(f"[叶子的逼] 生成失败: {exc}")
                return event.plain_result(f"[失败] {exc}")
            except Exception as exc:
                self._clear_cooldown(sender_id, reservation)
                logger.error(f"[叶子的逼] 未预期异常: {exc}", exc_info=True)
                return event.plain_result(f"[失败] 内部错误：{type(exc).__name__}")

        try:
            path = self._save_image(data, preset_key)
        except (OSError, ValueError, TypeError) as exc:
            self._clear_cooldown(sender_id, reservation)
            logger.error(f"[叶子的逼] 图片保存失败: {exc}", exc_info=True)
            return event.plain_result("[失败] 图片保存失败，请检查插件数据目录。")
        self._last_image[str(sender_id)] = str(path)
        if warning:
            logger.info(f"[叶子的逼] {label} 参数提示: {warning}")
        return event.image_result(str(path))

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

    # ==================== 隐写：生图 + 载体图库结合 ====================

    @staticmethod
    def _find_image_segment(event: AstrMessageEvent):
        """从消息或引用消息中提取 Image 段的 url，返回 url 或 None。"""
        try:
            from astrbot.api.message_components import Image as CompImage, Reply
        except ImportError:
            return None
        for segment in event.message_obj.message:
            if isinstance(segment, Reply) and hasattr(segment, 'chain'):
                for sub in segment.chain:
                    if isinstance(sub, CompImage) and getattr(sub, 'url', None):
                        return sub.url
            if isinstance(segment, CompImage) and getattr(segment, 'url', None):
                return segment.url
        return None

    async def _download_to_bytes(self, url: str) -> bytes:
        """下载 URL 内容为 bytes，支持 http 和 base64。"""
        if url.startswith('base64://'):
            return base64.b64decode(url[len('base64://'):])
        if url.startswith('http'):
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    return await resp.read()
        # 本地文件
        path = Path(url.removeprefix('file://'))
        return path.read_bytes()

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
    async def cmd_steg_hide(self, event: AstrMessageEvent, args: str = ""):
        """生成图片并隐藏进预设图库的载体图中，只发送载体图。

        用法：/nai隐写 [密码] 画面描述
        流程：调 NovelAI 生成图片 → 从载体图库随机取图 → 把生成的图隐藏进载体图 → 只发载体图
        其他人看到的是一张普通的预设图片，但里面藏着生成的图。
        用 /nai提取 可以还原出生成的图片。
        """
        if not self._api.configured:
            yield event.plain_result(
                "[失败] 插件未配置 API 地址或密钥，请在管理面板填写后重试。"
            )
            return

        raw = str(args or "").strip()
        if not raw:
            yield event.plain_result(
                "请描述要画的内容。例如：\n"
                "  /nai隐写 1girl, long hair, white dress\n"
                "  /nai隐写 我的密码 1girl, long hair\n"
                "生成的图片会隐藏进预设图库的载体图中，只发送载体图。\n"
                "用 /nai提取 [密码] 可还原出原始生成图。"
            )
            return

        sender_id = self._sender_id(event)

        # 解析密码和画面描述：如果第一段词不是预设编号，且整体不像纯描述，
        # 则把第一段当作密码，其余当作描述。
        password = None
        description = raw
        parts = raw.split(maxsplit=1)
        if parts and not parts[0].isdecimal() and not raw.startswith("-"):
            # 第一段不是纯数字（不是预设编号），当作密码
            password = parts[0]
            description = parts[1] if len(parts) > 1 else ""
            if password.lower() in {"不需要", "无", "no", "不加密"}:
                password = None

        if not description:
            yield event.plain_result("[失败] 缺少画面描述。用法：/nai隐写 [密码] 画面描述")
            return

        # 检查载体图库是否有图
        try:
            cover_path = self._pick_random_cover()
        except ValueError as exc:
            yield event.plain_result(f"[失败] {exc}")
            return

        # 解析预设和尺寸（复用 /nai 的参数解析逻辑）
        remaining, preset_key, size, warning = self._parse_args(
            description, self._user_presets.get(sender_id)
        )
        if not remaining:
            yield event.plain_result("[失败] 只填了参数，缺少画面描述。")
            return

        blocked = self._cooldown_remaining(sender_id)
        if blocked > 0:
            yield event.plain_result(f"[提示] 冷却中，请 {blocked} 秒后再试。")
            return

        reservation = time.time()
        self._last_call[sender_id] = reservation

        current_preset_number = preset_number(preset_key)
        yield event.plain_result(
            "[隐写绘图] 正在生成并隐写，请稍候。\n"
            f"预设：{current_preset_number} = {PRESETS[preset_key]['label']}\n"
            f"尺寸：{size}\n"
            f"载体：{cover_path.name}\n"
            f"加密：{'是' if password else '否'}"
        )

        # Step 1: 调 NovelAI 生成图片
        try:
            description_tags, note = await to_tags(
                self.context, remaining, self._use_llm_translate()
            )
        except Exception as exc:
            self._clear_cooldown(sender_id, reservation)
            logger.error(f"[叶子的逼] 描述转换异常: {exc}", exc_info=True)
            yield event.plain_result("[失败] 描述转换失败，请稍后重试。")
            return
        if note:
            warning = "；".join(part for part in (warning, note) if part)
        if not str(description_tags or "").strip():
            self._clear_cooldown(sender_id, reservation)
            detail = warning or "没有可用于绘图的英文标签"
            yield event.plain_result(f"[失败] {detail}。")
            return

        variant_index = self._next_variant_index(sender_id, preset_key)
        face_enabled = self._face_variation_enabled(sender_id)
        prompt, face_negative = build_prompt(
            preset_key,
            description_tags,
            index=variant_index,
            include_face=face_enabled,
            custom_artist=self._artist_string(sender_id),
        )
        negative = build_negative(
            preset_key,
            self._allow_nsfw(sender_id),
            self.config.get("extra_negative", ""),
            face_negative,
            description_tags,
            include_face=face_enabled,
        )

        async with self._semaphore:
            try:
                loop = asyncio.get_running_loop()
                generated_data = await loop.run_in_executor(
                    None,
                    lambda: self._api.generate(
                        prompt, negative, size, retries=self._retries()
                    ),
                )
            except NaiAPIError as exc:
                self._clear_cooldown(sender_id, reservation)
                logger.error(f"[叶子的逼] 生成失败: {exc}")
                yield event.plain_result(f"[失败] {exc}")
                return
            except Exception as exc:
                self._clear_cooldown(sender_id, reservation)
                logger.error(f"[叶子的逼] 未预期异常: {exc}", exc_info=True)
                yield event.plain_result(f"[失败] 内部错误：{type(exc).__name__}")
                return

        # Step 2: 保存生成的图片
        try:
            generated_path = self._save_image(generated_data, preset_key)
        except (OSError, ValueError, TypeError) as exc:
            self._clear_cooldown(sender_id, reservation)
            logger.error(f"[叶子的逼] 图片保存失败: {exc}", exc_info=True)
            yield event.plain_result("[失败] 图片保存失败，请检查插件数据目录。")
            return

        # Step 3: 把生成的图片隐藏进载体图
        session_id = uuid.uuid4().hex[:8]
        output_path = self._steg_dir / f"{session_id}_stego.png"
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: hide_file_into_image(
                    cover_path=cover_path,
                    file_path=generated_path,
                    file_name=f"nai_{preset_key}_{time.time_ns()}.png",
                    output_path=output_path,
                    encrypt=bool(password),
                    password=password,
                ),
            )
        except Exception as exc:
            logger.error(f"[叶子的逼] 隐写失败: {exc}", exc_info=True)
            yield event.plain_result(f"[失败] 隐写失败：{exc}")
            return

        # Step 4: 只发送载体图（生成的图片已隐藏其中）
        self._last_image[sender_id] = str(output_path)
        logger.info(
            f"[叶子的逼] 隐写完成 sender={sender_id} preset={preset_key} "
            f"cover={cover_path.name}"
        )
        yield event.image_result(str(output_path))

    @filter.command("nai提取", alias={"nai_extract", "naiunhide"})
    async def cmd_steg_extract(self, event: AstrMessageEvent, args: str = ""):
        """从载体图中提取隐藏的生成图片，可选密码解密。

        用法：回复一张图片 + /nai提取 [密码]
        """
        password = str(args or "").strip()
        password = password if password and password.lower() not in {"不需要", "无", "no"} else None

        image_url = self._find_image_segment(event)
        if not image_url:
            yield event.plain_result(
                "请上传或引用一张图片后再使用 /nai提取。\n"
                "用法：回复图片 + /nai提取 [密码]"
            )
            return

        yield event.plain_result("收到。正在提取隐藏文件，请稍候...")

        session_id = uuid.uuid4().hex[:8]
        img_path = self._steg_dir / f"{session_id}_cover.png"
        try:
            loop = asyncio.get_running_loop()
            img_data = await loop.run_in_executor(None, self._download_to_bytes, image_url)
            await loop.run_in_executor(None, img_path.write_bytes, img_data)

            result_path = await loop.run_in_executor(
                None,
                lambda: extract_file_from_image(
                    image_path=img_path,
                    output_dir=self._steg_dir,
                    password=password,
                ),
            )

            # 提取出来的文件就是原始生成的图片，直接发送
            yield event.image_result(str(result_path))
            logger.info(f"[叶子的逼] 提取完成 file={Path(result_path).name}")

            # 清理提取的临时文件
            try:
                result_path.unlink()
            except OSError:
                pass

        except ValueError as exc:
            yield event.plain_result(f"提取失败：{exc}")
        except Exception as exc:
            logger.error(f"[叶子的逼] 提取失败: {exc}", exc_info=True)
            yield event.plain_result(f"[失败] 提取失败：{exc}")
        finally:
            try:
                if img_path.exists():
                    img_path.unlink()
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
        logger.info("[叶子的逼] 插件已卸载")
