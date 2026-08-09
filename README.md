# 叶子的逼

基于 NovelAI Diffusion 4.5 的 AstrBot 绘画插件，内置画师串预设、中文标签转换和失败重试。

## 指令

```
/nai 1                                   选择第一个预设
/nai <画面描述>                          使用已选预设生成
/nai 1 <描述>                            选择第一个预设并立即生成
/nai -风格 1 <描述>                      完整参数写法
/nai -风格 hiten <描述>                  也可使用原英文名称
/nai -尺寸 方图 <描述>                   指定尺寸
/nai -风格 mature -尺寸 横图 <描述>      同时指定
/nai预设                                 查看预设清单与当前默认值
/nainsfw 开                              为当前用户开启 NSFW
/nainsfw 关                              为当前用户关闭 NSFW
/nainsfw 状态                            查看当前用户的 NSFW 状态
/nainsfw 默认                            恢复管理面板默认值
```

参数别名：`-风格` = `-预设` = `-style` = `-p`，`-尺寸` = `-size` = `-s`。
执行 `/nai预设` 会按 `1 = 老五样（通用美脸） [laowuyang]` 的格式显示编号。
单独发送 `/nai 1` 会保存个人选择，之后发送
`/nai 画面描述` 即可绘图；也可以使用 `/nai 1 描述` 一步完成选择和绘图。

## 中文描述

支持直接用中文，无需自己写英文标签：

```
/nai 1
/nai 长发女孩

/nai 2 白发少女
/nai 3 夜景旗袍
```

个人选择保留到插件重载；插件重载后恢复管理面板设置的默认预设。

## NSFW 开关

发送 `/nainsfw 开` 后，仅当前用户的绘图不再追加内置 NSFW 压制词。该设置不会影响
其他用户，也不会修改管理面板配置。使用 `/nainsfw 关` 可强制关闭，使用
`/nainsfw 默认` 可恢复管理面板中的 `allow_nsfw` 设置。

个人 NSFW 设置保留到插件重载。

## 生成反馈

绘图指令通过参数检查后，机器人会立即回复“指令已生效，正在生成”，并显示本次实际
使用的预设、尺寸和 NSFW 状态。生成完成后再发送图片；生成失败时会发送具体原因。

转换分两层：先查内置词典（约 250 条，覆盖发型发色、瞳色、表情、服装、姿势、场景、
光照、体型、颜色），词典未覆盖的部分再交给 AstrBot 的 LLM 转成 danbooru 标签。

LLM 不可用或未配置时自动降级为仅词典结果，不阻断出图，未识别的部分会在日志中提示。
关闭 `llm_translate` 可完全禁用 LLM 调用。

英文输入直接透传，不经过任何转换。

## 画风预设

| 编号 | 键 | 说明 |
|---|---|---|
| `1` | `laowuyang` | 老五样，社区通用美脸基础串，以 ciloranko 为主力 |
| `2` | `hiten` | 柔和日系，明亮淡彩 |
| `3` | `pop` | 波普撞色，扁平色块配颜料飞溅 |
| `4` | `ghostblade` | 鬼刀厚涂，wlop 系冷调强光影 |
| `5` | `mature` | 成熟妩媚，成年体态与细长眼型 |
| `6` | `watercolor` | 水彩透明，湿画法与颜色渗染 |
| `7` | `retro` | 复古赛璐璐，90 年代动画质感 |
| `8` | `oil` | 厚涂油画，可见笔触与厚涂肌理 |

## 尺寸

支持中文别名 `竖图` / `方图` / `横图` / `大图`，或直接写 `832x1216`。

宽高须为 64 的倍数，超出范围或非法值会回退到默认尺寸，不会向上游发送无效请求。

## 配置

在管理面板填写：

- `api_base` — OpenAI 兼容端点前缀，不含 `/v1/images/generations`
- `api_key` — 访问令牌，必填
- `model` — 默认 `nai-diffusion-4-5-full`
- `default_size` / `default_preset` — 缺省参数
- `cooldown` — 用户冷却秒数，0 为不限
- `max_concurrent` — 并发上限，防止打满上游配额
- `allow_nsfw` — 个人未执行 `/nainsfw` 时使用的默认值；关闭时加入 NSFW 压制标签
- `timeout` — 单次请求超时秒数，范围 1~600
- `retries` / `retry_backoff` — 临时网络故障的尝试次数与指数退避基数
- `keep_images` — 关闭时只保留最近 20 张出图，开启后不自动清理
- `extra_negative` — 追加到内置负面词之后
- `llm_translate` — 是否使用 AstrBot LLM 补充翻译词典未覆盖的中文

## 提示词约定

新增预设时需遵守以下约束，否则出图质量不可控：

**质量词必须用 NAI4.5 体系。** `amazing quality, very aesthetic, absurdres` 有效，
NAI3/SD 的 `masterpiece, best quality` 在 4.5 上不起作用。

**数值权重不得超过 1.5。** `1.2::tag::` 可用，`2.0::tag::` 会推崩去噪过程直接产出纯噪点。
法典里的 `3::artist:xxx::` 是配合特定采样器和步数的，裸用会炸。

**负面词的重点是完成度而非「丑」。** `very displeasing` 和 `bad quality` 是 NAI 自带的
美学评分标签，对成品率影响最大；`sketch` / `unfinished` / `washed out` 压制未画完的线稿感。

**风格词避免语义冲突。** `thick brushstrokes` 与 `soft blended shading` 并存会互相抵消，
多层花括号只会放大冲突。

**平涂系画师与精细渲染互斥。** modare、mignon、kukka 这类画师本身是低对比风格，
只适合 `watercolor` 和极简类预设。

## 依赖

```
requests
```

## 测试

```bash
python test_presets.py
python test_translator.py
```

`test_presets.py` 覆盖预设名解析、尺寸边界、提示词组装、负面词冲突剔除、
权重安全性与风格词冲突检查。

`test_translator.py` 覆盖中文检测、词典长词优先与去重、残留识别、
LLM 输出清洗（剔除解释文字、权重符号、质量词、画师串）与故障降级路径。
LLM 部分用桩对象模拟，不产生网络请求。
