/**
 * 绘台 (Studio) - 全功能一体化工坊核心驱动脚本
 * 原生现代 ESM 架构，零外部依赖，极速毫秒级响应
 */

// 随机场景由服务端 composition_style 法典提供；仅离线预览时使用兜底。
const FALLBACK_SAMPLES = [
  "古风黑金汉服，华美刺绣，绝美少女，手持折扇，回眸微光，精致五官，唯美仙侠",
  "雨夜霓虹街头，长发白发少女，黑色机能风风衣，湿润发丝，侧光特写，电影级光影",
  "赛博朋克机能少女，机械义肢，荧光眼眸，发光线缆，虚幻引擎5渲染，光线追踪",
  "日系水彩透明感，夏日微风，JK制服少女，向日葵花海，柔和逆光，治愈唯美",
  "深海幽蓝幻境，漂浮发丝，发光水母，梦幻水波倒影，空灵少女，精致光斑",
  "复古洛丽塔洋装，红酒玫瑰，哥特华丽少女，精致蕾丝发带，微光暗调，厚涂油画",
  "星际战舰舰桥，星云璀璨，星际指挥官少女，高科技战术目镜，全息投影光辉",
];

function createFallbackBridge() {
  const message = "请在 AstrBot 插件详情页打开绘台";
  const fail = async () => {
    throw new Error(message);
  };
  return {
    ready: async () => ({ isDark: true, pageTitle: "绘台" }),
    apiGet: async (endpoint) => {
      if (endpoint !== "bootstrap") {
        throw new Error(message);
      }
      return {
        configured: true,
        model: "nai-diffusion-4-5-full",
        default_preset: "iceblue",
        default_size: "832x1216",
        allow_nsfw: false,
        enable_face_variation: true,
        presets: [
          { number: 0, key: "none", label: "无预设", faces: 0 },
          { number: 1, key: "iceblue", label: "冰蓝柔光（日系）", faces: 12 },
          { number: 2, key: "cinematic", label: "冷调电影厚涂", faces: 36 },
          { number: 3, key: "neon_flat", label: "霓虹平涂", faces: 36 },
          { number: 4, key: "glossy_mature", label: "高光成熟人物", faces: 36 },
          { number: 5, key: "dark_portrait", label: "暗夜轻熟肖像", faces: 48 },
          { number: 6, key: "golden_backlight", label: "暖金逆光", faces: 12 },
          { number: 7, key: "dreamy_floral", label: "暮光花境", faces: 12 },
          { number: 8, key: "pastel_chibi", label: "粉彩无描边 Q版", faces: 12 },
          { number: 9, key: "filmgrain_illustration", label: "青雾胶片插画", faces: 12 },
        ],
        sizes: [
          { key: "832x1216", label: "竖图", hint: "832×1216" },
          { key: "832x832", label: "方图", hint: "832×832" },
          { key: "1216x832", label: "横图", hint: "1216×832" },
          { key: "1024x1024", label: "大图", hint: "1024×1024" },
        ],
        generation_params: {
          samplers: ["k_euler", "k_euler_ancestral", "k_dpmpp_2m", "k_dpmpp_2s_ancestral", "k_dpmpp_sde", "ddim_v3", "ddim"],
          noise_schedules: ["native", "karras", "exponential"],
          defaults: { steps: 28, scale: 5, cfg_rescale: 0, seed: -1, sampler: "k_euler_ancestral", noise_schedule: "native", smea: false, sm_dyn: false, quality_toggle: true },
        },
        composition_scenes: FALLBACK_SAMPLES.map((prompt, index) => ({
          index,
          title: `兜底灵感 ${index + 1}`,
          prompt,
          entry_id: `fallback_${index + 1}`,
        })),
        inspiration_scenes: FALLBACK_SAMPLES.map((prompt, index) => ({
          index,
          title: `兜底灵感 ${index + 1}`,
          prompt,
          entry_id: `fallback_${index + 1}`,
        })),
        gallery: [],
        covers: [],
      };
    },
    apiPost: fail,
    upload: fail,
    download: fail,
  };
}

const bridge = window.AstrBotPluginPage || createFallbackBridge();

// 全局响应式状态
const state = {
  configured: false,
  preset: "iceblue",
  size: "832x1216",
  currentName: "",
  stegoName: "",
  presets: [],
  sizes: [],
  generationParams: {
    samplers: [],
    noiseSchedules: [],
    defaults: {},
  },
  compositionScenes: [],
  inspirationScenes: [],
  selectedSceneIndex: null,
  gallery: [],
  covers: [],
  thumbs: new Map(),
  isBusy: false,
};

// DOM 元素引用表
const els = {
  // 顶栏
  apiStatus: document.getElementById("status-api"),
  statusDot: document.getElementById("status-dot"),
  modelStatus: document.getElementById("status-model"),
  galleryCount: document.getElementById("status-gallery"),
  coverCount: document.getElementById("status-covers"),
  tabCoverCount: document.getElementById("tab-cover-count"),
  
  // 表单与输入
  form: document.getElementById("draw-form"),
  prompt: document.getElementById("prompt"),
  btnClearPrompt: document.getElementById("btn-clear-prompt"),
  btnRandomPrompt: document.getElementById("btn-random-prompt"),
  btnRandomArtist: document.getElementById("btn-random-artist"),
  quickTagsContainer: document.getElementById("quick-tags-container"),
  artists: document.getElementById("artists"),
  artistChips: document.querySelectorAll(".artist-chip-pill"),
  nsfw: document.getElementById("nsfw"),
  face: document.getElementById("face"),
  stego: document.getElementById("stego"),
  stegoPasswordField: document.getElementById("stego-password-field"),
  stegoPassword: document.getElementById("stego-password"),
  drawButton: document.getElementById("draw-button"),
  drawSpinner: document.getElementById("draw-spinner"),
  drawBtnIcon: document.getElementById("draw-btn-icon"),
  drawBtnText: document.getElementById("draw-btn-text"),
  formHint: document.getElementById("form-hint"),
  presetGrid: document.getElementById("preset-grid"),
  sizeRow: document.getElementById("size-row"),
  presetSummary: document.getElementById("preset-summary"),
  sizeSummary: document.getElementById("size-summary"),
  advancedSummary: document.getElementById("advanced-summary"),
  steps: document.getElementById("steps"),
  stepsValue: document.getElementById("steps-value"),
  scale: document.getElementById("scale"),
  scaleValue: document.getElementById("scale-value"),
  cfgRescale: document.getElementById("cfg-rescale"),
  cfgRescaleValue: document.getElementById("cfg-rescale-value"),
  seed: document.getElementById("seed"),
  btnRandomSeed: document.getElementById("btn-random-seed"),
  sampler: document.getElementById("sampler"),
  noiseSchedule: document.getElementById("noise-schedule"),
  qualityToggle: document.getElementById("quality-toggle"),
  smea: document.getElementById("smea"),
  smDyn: document.getElementById("sm-dyn"),
  extraNegative: document.getElementById("extra-negative"),
  btnResetParams: document.getElementById("btn-reset-params"),

  // 画布与主结果区
  mainStage: document.getElementById("main-stage"),
  historyFilmstrip: document.getElementById("history-filmstrip"),
  canvasViewport: document.getElementById("canvas-viewport"),
  artworkFrame: document.getElementById("artwork-frame"),
  resultImage: document.getElementById("result-image"),
  resultEmpty: document.getElementById("result-empty"),
  resultDock: document.getElementById("result-dock"),
  promptInspectorBox: document.getElementById("prompt-inspector-box"),
  downloadResult: document.getElementById("download-result"),
  downloadStego: document.getElementById("download-stego"),
  sheetPreset: document.getElementById("sheet-preset"),
  sheetSize: document.getElementById("sheet-size"),
  sheetNsfw: document.getElementById("sheet-nsfw"),
  sheetFace: document.getElementById("sheet-face"),
  sheetGeneration: document.getElementById("sheet-generation"),
  sheetPrompt: document.getElementById("sheet-prompt"),
  sheetNegative: document.getElementById("sheet-negative"),
  resultNote: document.getElementById("result-note"),
  btnCopyPrompt: document.getElementById("btn-copy-prompt"),
  btnCopyNegative: document.getElementById("btn-copy-negative"),

  // 全屏灯箱 Modal
  lightboxModal: document.getElementById("lightbox-modal"),
  lightboxBackdrop: document.getElementById("lightbox-backdrop"),
  lightboxClose: document.getElementById("lightbox-close"),
  lightboxImg: document.getElementById("lightbox-img"),

  // 顶栏模式导航
  tabs: document.querySelectorAll(".nav-menu-btn"),
  tabPanels: document.querySelectorAll(".view-mode-panel"),
  btnToggleTheme: document.getElementById("btn-toggle-theme"),

  // 画廊与载体
  gallery: document.getElementById("gallery"),
  btnRefreshGallery: document.getElementById("btn-refresh-gallery"),
  covers: document.getElementById("covers"),
  coverFile: document.getElementById("cover-file"),
  coverDropZone: document.getElementById("cover-drop-zone"),

  // 隐写拆封
  extractDropZone: document.getElementById("extract-drop-zone"),
  extractFile: document.getElementById("extract-file"),
  extractPassword: document.getElementById("extract-password"),
  extractHint: document.getElementById("extract-hint"),
  extractResultPanel: document.getElementById("extract-result-panel"),
  extractPreviewImg: document.getElementById("extract-preview-img"),
  btnDownloadExtracted: document.getElementById("btn-download-extracted"),

  // Toast 悬浮通知
  toast: document.getElementById("toast"),
};

function unwrap(payload) {
  if (!payload || typeof payload !== "object") {
    return payload;
  }
  if (payload.status === "error") {
    throw new Error(payload.message || "请求遇到异常");
  }
  if (payload.status === "ok" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

function errorMessage(error) {
  if (!error) return "请求遇到异常";
  if (typeof error === "string") return error;
  const text = error.message || "请求遇到异常";
  if (/timeout|timed out|exceeded/i.test(text)) {
    return "请求超时，请稍后重试。若刚开启角色查询，普通画面描述不应再被外网拖住";
  }
  return text;
}

function showToast(message, kind = "info") {
  if (!els.toast) return;
  els.toast.hidden = false;
  els.toast.className = `studio-toast-capsule ${kind === "error" ? "error" : ""}`.trim();
  els.toast.textContent = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 4000);
}

function setBusy(busy) {
  state.isBusy = busy;
  els.drawButton.disabled = busy;
  els.drawSpinner.hidden = !busy;
  if (els.drawBtnIcon) els.drawBtnIcon.style.display = busy ? "none" : "block";
  if (els.drawBtnText) els.drawBtnText.textContent = busy ? "正在渲染生成中..." : "立即渲染生成";
  if (els.mainStage) {
    els.mainStage.classList.toggle("is-waiting", busy);
    if (busy) els.mainStage.scrollTop = 0;
  }
  const title = els.resultEmpty && els.resultEmpty.querySelector(".empty-lead-title");
  const caption = els.resultEmpty && els.resultEmpty.querySelector(".empty-sub-caption");
  if (title) title.textContent = busy ? "正在渲染" : "暗房巨幕就绪";
  if (caption) {
    caption.textContent = busy
      ? "请稍候，成图完成后会显示在这里。"
      : "在左侧构思画面并点击“立即渲染生成”，高清成图将在此处完整展出。";
  }
}

function dataUrl(image) {
  return `data:${image.mime || "image/png"};base64,${image.data}`;
}

async function apiGet(endpoint, params) {
  return unwrap(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  return unwrap(await bridge.apiPost(endpoint, body));
}

// 顶栏模式切换
function setupTabs() {
  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetTab = tab.dataset.tab;
      els.tabs.forEach((t) => {
        const isMatch = t === tab;
        t.classList.toggle("active", isMatch);
        t.setAttribute("aria-selected", isMatch ? "true" : "false");
      });
      els.tabPanels.forEach((p) => {
        const isActive = p.id === targetTab;
        p.classList.toggle("active", isActive);
        p.hidden = !isActive;
      });
    });
  });
}

// 渲染画风预设矩阵（专属艺术微缩色板）
function renderPresets(presets) {
  els.presetGrid.replaceChildren();
  for (const item of presets) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `preset-chip-card ${item.key === state.preset ? "active" : ""}`;
    card.dataset.key = item.key;
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", item.key === state.preset ? "true" : "false");

    const swatch = document.createElement("div");
    swatch.className = `preset-art-swatch swatch-${item.key}`;

    const metaRow = document.createElement("div");
    metaRow.className = "preset-meta-row";

    const seqSpan = document.createElement("span");
    seqSpan.className = "preset-seq";
    seqSpan.textContent = `#${item.number}`;

    const titleSpan = document.createElement("span");
    titleSpan.className = "preset-name";
    titleSpan.textContent = item.label.split("（")[0];
    card.title = item.label;

    metaRow.appendChild(seqSpan);
    metaRow.appendChild(titleSpan);

    card.appendChild(swatch);
    card.appendChild(metaRow);

    card.addEventListener("click", () => {
      state.preset = item.key;
      els.presetSummary.textContent = item.label;
      els.presetGrid.querySelectorAll(".preset-chip-card").forEach((c) => {
        const isMatch = c.dataset.key === item.key;
        c.classList.toggle("active", isMatch);
        c.setAttribute("aria-checked", isMatch ? "true" : "false");
      });
    });

    els.presetGrid.appendChild(card);
  }
}

// 渲染画幅尺寸选择矩阵（微缩矢量线框）
function renderSizes(sizes) {
  els.sizeRow.replaceChildren();
  for (const item of sizes) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `size-wireframe-card ${item.key === state.size ? "active" : ""}`;
    card.dataset.key = item.key;
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", item.key === state.size ? "true" : "false");

    let boxClass = "box-portrait";
    if (item.key === "832x832") boxClass = "box-square";
    else if (item.key === "1216x832") boxClass = "box-landscape";
    else if (item.key === "1024x1024") boxClass = "box-large";

    const iconWrap = document.createElement("div");
    iconWrap.className = "ratio-wireframe-box";
    const box = document.createElement("div");
    box.className = `wireframe-shape ${boxClass}`;
    iconWrap.appendChild(box);

    const nameSpan = document.createElement("span");
    nameSpan.className = "size-title";
    nameSpan.textContent = item.label;

    const resSpan = document.createElement("span");
    resSpan.className = "size-dim";
    resSpan.textContent = item.hint;

    card.appendChild(iconWrap);
    card.appendChild(nameSpan);
    card.appendChild(resSpan);

    card.addEventListener("click", () => {
      state.size = item.key;
      els.sizeSummary.textContent = `${item.label} (${item.hint})`;
      els.sizeRow.querySelectorAll(".size-wireframe-card").forEach((c) => {
        const isMatch = c.dataset.key === item.key;
        c.classList.toggle("active", isMatch);
        c.setAttribute("aria-checked", isMatch ? "true" : "false");
      });
    });

    els.sizeRow.appendChild(card);
  }
}

// 渲染近期成图历史档案胶卷 (Instant Filmstrip)
function renderGallery(items) {
  state.gallery = items || [];
  const count = state.gallery.length;
  if (els.galleryCount) els.galleryCount.textContent = count;

  els.gallery.replaceChildren();
  if (count === 0) {
    const emptyNotice = document.createElement("p");
    emptyNotice.className = "filmstrip-tip";
    emptyNotice.textContent = "暂无近期生成记录，在左侧描述画面后点击出图即可在此处即时展示。";
    els.gallery.appendChild(emptyNotice);
    return;
  }

  for (const item of state.gallery) {
    const card = document.createElement("div");
    card.className = "art-card-item";

    const img = document.createElement("img");
    img.className = "art-card-item__thumb";
    img.alt = item.name;
    img.loading = "lazy";

    if (state.thumbs.has(item.name)) {
      img.src = state.thumbs.get(item.name);
    } else {
      apiGet("preview", { name: item.name })
        .then((res) => {
          if (res?.image) {
            const url = dataUrl(res.image);
            state.thumbs.set(item.name, url);
            img.src = url;
          }
        })
        .catch(() => {});
    }

    const meta = document.createElement("div");
    meta.className = "art-card-item__meta";

    const presetName = document.createElement("span");
    presetName.className = "art-card-item__preset";
    presetName.textContent = item.preset || "成图";

    const timeSpan = document.createElement("span");
    timeSpan.className = "art-card-item__time";
    timeSpan.textContent = new Date(item.mtime * 1000).toLocaleTimeString();

    meta.appendChild(presetName);
    meta.appendChild(timeSpan);
    card.appendChild(img);
    card.appendChild(meta);

    // 点击胶卷卡片：在主画布中即时重放
    card.addEventListener("click", async () => {
      try {
        const res = await apiGet("preview", { name: item.name });
        if (res?.image) {
          state.currentName = item.name;
          state.stegoName = "";
          displayResultOnCanvas(res.image, {
            preset_label: item.preset || "历史归档",
            size: "自适应",
            nsfw: false,
            face_variation: true,
            prompt: "（该历史作品完整标签已安全归档）",
            negative: "—",
          });
          // 平滑滚动回顶部巨幕
          const scroller = document.querySelector(".workbench-main-stage");
          if (scroller) scroller.scrollTo({ top: 0, behavior: "smooth" });
          showToast(`已在画布中载入 ${item.name}`);
        }
      } catch (err) {
        showToast(`载入历史作品失败: ${errorMessage(err)}`, "error");
      }
    });

    els.gallery.appendChild(card);
  }
}

// 渲染载体图库列表
function renderCovers(items) {
  state.covers = items || [];
  const count = state.covers.length;
  if (els.coverCount) els.coverCount.textContent = count;
  if (els.tabCoverCount) els.tabCoverCount.textContent = count;

  els.covers.replaceChildren();
  if (count === 0) {
    const emptyNotice = document.createElement("p");
    emptyNotice.className = "vault-specs-text";
    emptyNotice.textContent = "载体库暂无图片。拖拽图片至上方磁吸区或点击上传。";
    els.covers.appendChild(emptyNotice);
    return;
  }

  for (const item of state.covers) {
    const card = document.createElement("div");
    card.className = "cover-card-box";

    const img = document.createElement("img");
    img.className = "cover-card-box__thumb";
    img.alt = item.name;
    img.loading = "lazy";

    if (state.thumbs.has(item.name)) {
      img.src = state.thumbs.get(item.name);
    } else {
      apiGet("preview", { name: item.name })
        .then((res) => {
          if (res?.image) {
            const url = dataUrl(res.image);
            state.thumbs.set(item.name, url);
            img.src = url;
          }
        })
        .catch(() => {});
    }

    const foot = document.createElement("div");
    foot.className = "cover-card-box__foot";

    const nameSpan = document.createElement("span");
    nameSpan.className = "cover-card-box__name";
    nameSpan.textContent = item.name;
    nameSpan.title = item.name;

    const btnDel = document.createElement("button");
    btnDel.type = "button";
    btnDel.className = "btn-del-action";
    btnDel.textContent = "删除";
    btnDel.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`确定要从载体图库中删除 ${item.name} 吗？`)) return;
      try {
        const res = await apiPost("covers/delete", { name: item.name });
        renderCovers(res.covers);
        showToast("已成功移除载体图片");
      } catch (err) {
        showToast(`删除失败: ${errorMessage(err)}`, "error");
      }
    });

    foot.appendChild(nameSpan);
    foot.appendChild(btnDel);
    card.appendChild(img);
    card.appendChild(foot);

    els.covers.appendChild(card);
  }
}

// 主画布呈现成图
function displayResultOnCanvas(imageObj, meta) {
  if (!imageObj || !imageObj.data) {
    throw new Error("出图成功但没有返回图片数据");
  }
  meta = meta || {};
  els.resultImage.src = dataUrl(imageObj);
  els.artworkFrame.hidden = false;
  if (els.resultEmpty) {
    els.resultEmpty.hidden = true;
    els.resultEmpty.style.display = "none";
  }
  els.resultDock.hidden = false;
  if (els.promptInspectorBox) els.promptInspectorBox.hidden = false;

  els.sheetPreset.textContent = meta.preset_label || meta.preset || "—";
  els.sheetSize.textContent = meta.size || "—";
  els.sheetNsfw.textContent = meta.nsfw ? "开启" : "关闭";
  els.sheetFace.textContent = meta.face_variation ? "启用" : "禁用";
  const generation = meta.generation_params || {};
  const generationSummary = [
    generation.steps ? `${generation.steps}步` : "默认步数",
    generation.scale !== undefined ? `CFG ${generation.scale}` : "默认CFG",
    generation.seed !== undefined && generation.seed !== -1 ? `种子 ${generation.seed}` : "随机种子",
  ].join(" · ");
  if (els.sheetGeneration) els.sheetGeneration.textContent = generationSummary;
  els.sheetPrompt.textContent = meta.prompt || "—";
  els.sheetNegative.textContent = meta.negative || "—";

  if (meta.note) {
    els.resultNote.textContent = meta.note;
    els.resultNote.hidden = false;
  } else {
    els.resultNote.hidden = true;
  }

  els.downloadResult.disabled = !state.currentName;
  els.downloadStego.hidden = !state.stegoName;
}

function applyGenerationDefaults(defaults) {
  const values = defaults || {};
  if (els.steps) els.steps.value = values.steps ?? 28;
  if (els.scale) els.scale.value = values.scale ?? 5;
  if (els.cfgRescale) els.cfgRescale.value = values.cfg_rescale ?? 0;
  if (els.seed) els.seed.value = values.seed ?? -1;
  if (els.sampler) els.sampler.value = values.sampler || "k_euler_ancestral";
  if (els.noiseSchedule) els.noiseSchedule.value = values.noise_schedule || "native";
  if (els.smea) els.smea.checked = Boolean(values.smea);
  if (els.smDyn) els.smDyn.checked = Boolean(values.sm_dyn);
  if (els.qualityToggle) els.qualityToggle.checked = values.quality_toggle !== false;
  if (els.extraNegative) els.extraNegative.value = "";
  updateGenerationLabels();
}

function updateGenerationLabels() {
  if (els.stepsValue) els.stepsValue.textContent = String(els.steps?.value || 28);
  if (els.scaleValue) els.scaleValue.textContent = Number(els.scale?.value || 5).toFixed(1);
  if (els.cfgRescaleValue) els.cfgRescaleValue.textContent = Number(els.cfgRescale?.value || 0).toFixed(2);
  if (els.advancedSummary) {
    els.advancedSummary.textContent = `${els.steps?.value || 28} 步 · CFG ${Number(els.scale?.value || 5).toFixed(1)}`;
  }
}

function readGenerationParams() {
  return {
    steps: Number(els.steps?.value || 28),
    scale: Number(els.scale?.value || 5),
    cfg_rescale: Number(els.cfgRescale?.value || 0),
    seed: Number(els.seed?.value || -1),
    sampler: els.sampler?.value || "k_euler_ancestral",
    noise_schedule: els.noiseSchedule?.value || "native",
    smea: Boolean(els.smea?.checked),
    sm_dyn: Boolean(els.smDyn?.checked),
    quality_toggle: Boolean(els.qualityToggle?.checked),
  };
}

function renderGenerationParams(data) {
  const params = data || {};
  state.generationParams = {
    samplers: params.samplers || [],
    noiseSchedules: params.noise_schedules || [],
    defaults: params.defaults || {},
  };
  if (els.sampler) {
    els.sampler.replaceChildren();
    for (const value of state.generationParams.samplers) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      els.sampler.appendChild(option);
    }
  }
  if (els.noiseSchedule) {
    els.noiseSchedule.replaceChildren();
    for (const value of state.generationParams.noiseSchedules) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      els.noiseSchedule.appendChild(option);
    }
  }
  applyGenerationDefaults(state.generationParams.defaults);
}

// 初始化引导数据
async function bootstrap() {
  try {
    const readyState = await bridge.ready();
    if (readyState && readyState.isDark !== undefined) {
      document.documentElement.setAttribute("data-theme", readyState.isDark ? "dark" : "light");
    }

    const data = await apiGet("bootstrap");
    state.configured = Boolean(data.configured);
    state.preset = data.default_preset || "iceblue";
    state.size = data.default_size || "832x1216";
    state.presets = data.presets || [];
    state.sizes = data.sizes || [];
    renderGenerationParams(data.generation_params);
    state.compositionScenes = data.composition_scenes || [];
    state.inspirationScenes = data.inspiration_scenes || [];

    els.apiStatus.textContent = state.configured ? "SYSTEM READY" : "NO API KEY";
    els.statusDot.className = `status-indicator-dot ${state.configured ? "ready" : "error"}`;
    if (els.modelStatus) els.modelStatus.textContent = data.model || "NAI 4.5";
    els.nsfw.checked = Boolean(data.allow_nsfw);
    els.face.checked = Boolean(data.enable_face_variation);

    renderPresets(state.presets);
    renderSizes(state.sizes);
    renderGallery(data.gallery);
    renderCovers(data.covers);

    const activePresetObj = state.presets.find((p) => p.key === state.preset);
    if (activePresetObj) els.presetSummary.textContent = activePresetObj.label;

    const activeSizeObj = state.sizes.find((s) => s.key === state.size);
    if (activeSizeObj) els.sizeSummary.textContent = `${activeSizeObj.label} (${activeSizeObj.hint})`;
  } catch (err) {
    els.apiStatus.textContent = "OFFLINE";
    els.statusDot.className = "status-indicator-dot error";
    showToast(`初始化失败: ${errorMessage(err)}`, "error");
  }
}

// 统一绑定交互事件
function setupEventListeners() {
  setupTabs();

  // 清空描述
  els.btnClearPrompt.addEventListener("click", () => {
    els.prompt.value = "";
    state.selectedSceneIndex = null;
    els.prompt.focus();
  });

  // 随机精选示例灵感；提交时仍按完整法典索引走显式随机模式。
  if (els.btnRandomPrompt) {
    els.btnRandomPrompt.addEventListener("click", () => {
      const samples = state.inspirationScenes.length
        ? state.inspirationScenes
        : (state.compositionScenes.length ? state.compositionScenes : FALLBACK_SAMPLES.map((prompt, index) => ({
            index,
            title: `兜底灵感 ${index + 1}`,
            prompt,
          })));
      const selected = samples[Math.floor(Math.random() * samples.length)];
      els.prompt.value = selected.prompt;
      state.selectedSceneIndex = Number.isInteger(selected.index) ? selected.index : null;
      els.prompt.focus();
      showToast(selected.title ? `已抽取精选灵感：${selected.title}` : "已注入兜底灵感画面！");
    });
  }

  if (els.btnRandomArtist) {
    els.btnRandomArtist.addEventListener("click", async () => {
      try {
        const data = await apiPost("random-artist", {});
        els.artists.value = data.text || "";
        els.artists.focus();
        showToast(data.label ? `已抽取实测画师串：${data.label}` : "已注入随机画师串");
      } catch (error) {
        showToast(error.message || "随机画师串失败", "error");
      }
    });
  }

  // 快捷灵感词点击追加
  if (els.quickTagsContainer) {
    els.quickTagsContainer.addEventListener("click", (e) => {
      const tag = e.target.closest(".inspire-tag-pill");
      if (!tag) return;
      const tagContent = tag.dataset.tag;
      if (!tagContent) return;
      const currentVal = els.prompt.value.trim();
      if (currentVal) {
        els.prompt.value = `${currentVal}, ${tagContent}`;
      } else {
        els.prompt.value = tagContent;
      }
      els.prompt.focus();
      state.selectedSceneIndex = null;
      showToast(`已追加灵感：${tag.textContent.trim()}`);
    });
  }

  // 快捷画师标签追加
  els.artistChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const artist = chip.dataset.artist;
      if (!artist) return;
      const currentVal = els.artists.value.trim();
      if (currentVal) {
        if (!currentVal.includes(artist)) {
          els.artists.value = `${currentVal}, ${artist}`;
        }
      } else {
        els.artists.value = artist;
      }
      els.artists.focus();
      showToast(`已追加画师：${artist}`);
    });
  });

  // 快捷出图：Ctrl + Enter / Cmd + Enter
  els.prompt.addEventListener("input", () => {
    state.selectedSceneIndex = null;
  });

  els.prompt.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!state.isBusy) {
        els.form.requestSubmit();
      }
    }
  });

  // 隐写密码字段展开联动
  els.stego.addEventListener("change", () => {
    els.stegoPasswordField.hidden = !els.stego.checked;
  });

  // 切换深色/浅色模式
  els.btnToggleTheme.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
    const nextTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nextTheme);
  });

  // 复制提示词
  els.btnCopyPrompt.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.sheetPrompt.textContent);
      showToast("已复制正面标签到剪贴板");
    } catch {
      showToast("复制失败，请手动选取", "error");
    }
  });

  els.btnCopyNegative.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.sheetNegative.textContent);
      showToast("已复制负面标签到剪贴板");
    } catch {
      showToast("复制失败，请手动选取", "error");
    }
  });

  // 点击成图全屏灯箱放大预览
  if (els.resultImage && els.lightboxModal) {
    els.resultImage.addEventListener("click", () => {
      if (els.resultImage.src && !els.resultImage.hidden) {
        els.lightboxImg.src = els.resultImage.src;
        els.lightboxModal.hidden = false;
      }
    });

    const closeLightbox = () => {
      els.lightboxModal.hidden = true;
      els.lightboxImg.src = "";
    };

    els.lightboxClose.addEventListener("click", closeLightbox);
    els.lightboxBackdrop.addEventListener("click", closeLightbox);
  }

  // 提交出图表单
  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.isBusy) return;

    const promptVal = els.prompt.value.trim();
    if (!promptVal) {
      showToast("请填写画面描述后再出图", "error");
      els.prompt.focus();
      return;
    }

    setBusy(true);
    els.formHint.textContent = "正在转译中文并向 NovelAI 4.5 请求高清渲染...";

    try {
      const payload = {
        prompt: promptVal,
        random_scene: state.selectedSceneIndex !== null,
        scene_index: state.selectedSceneIndex,
        preset: state.preset,
        size: state.size,
        artists: els.artists.value.trim(),
        nsfw: els.nsfw.checked,
        face_variation: els.face.checked,
        generation_params: readGenerationParams(),
        extra_negative: els.extraNegative?.value.trim() || "",
        stego: els.stego.checked,
        stego_password: els.stegoPassword.value.trim(),
      };

      const result = await apiPost("generate", payload);
      if (!result || !result.image) {
        throw new Error((result && result.message) || "出图接口没有返回图片");
      }
      state.currentName = result.name || "";
      state.stegoName = result.stego?.ok ? result.stego.name : "";
      displayResultOnCanvas(result.image, result);
      state.selectedSceneIndex = null;
      if (result.name) {
        state.thumbs.set(result.name, dataUrl(result.image));
      }
      if (result.gallery) {
        renderGallery(result.gallery);
      }
      showToast("渲染完成，杰作已呈现！");
    } catch (err) {
      showToast(`渲染失败: ${errorMessage(err)}`, "error");
    } finally {
      setBusy(false);
      els.formHint.textContent = "中文将由智能翻译引擎自动转为官方高质量英文标签";
    }
  });

  [els.steps, els.scale, els.cfgRescale].forEach((input) => {
    input?.addEventListener("input", updateGenerationLabels);
  });
  els.btnRandomSeed?.addEventListener("click", () => {
    els.seed.value = String(Math.floor(Math.random() * 4294967295));
  });
  els.btnResetParams?.addEventListener("click", () => {
    applyGenerationDefaults(state.generationParams.defaults);
    showToast("已恢复推荐参数");
  });

  // 下载成图
  els.downloadResult.addEventListener("click", async () => {
    if (!state.currentName) return;
    try {
      if (typeof bridge.download === "function") {
        await bridge.download("download", { name: state.currentName }, state.currentName);
      } else {
        const link = document.createElement("a");
        link.href = els.resultImage.src;
        link.download = state.currentName;
        link.click();
      }
    } catch (err) {
      showToast(`下载失败: ${errorMessage(err)}`, "error");
    }
  });

  // 下载隐写封包
  els.downloadStego.addEventListener("click", async () => {
    if (!state.stegoName) return;
    try {
      if (typeof bridge.download === "function") {
        await bridge.download("download", { name: state.stegoName }, state.stegoName);
      } else {
        showToast("正在下载隐写封包...");
      }
    } catch (err) {
      showToast(`下载失败: ${errorMessage(err)}`, "error");
    }
  });

  // 刷新画廊
  els.btnRefreshGallery.addEventListener("click", async () => {
    try {
      const res = await apiGet("gallery");
      renderGallery(res.gallery);
      showToast("画廊档案库已刷新");
    } catch (err) {
      showToast(`刷新失败: ${errorMessage(err)}`, "error");
    }
  });

  // 上传载体
  async function handleCoverUpload(file) {
    if (!file) return;
    try {
      showToast(`正在上传载体图 ${file.name}...`);
      const res = await bridge.upload("covers/upload", file, {});
      const data = unwrap(res);
      renderCovers(data.covers);
      showToast("载体图上传成功！");
    } catch (err) {
      showToast(`上传载体失败: ${errorMessage(err)}`, "error");
    }
  }

  els.coverFile.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) handleCoverUpload(file);
    e.target.value = "";
  });

  els.coverDropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    els.coverDropZone.classList.add("dragover");
  });
  els.coverDropZone.addEventListener("dragleave", () => {
    els.coverDropZone.classList.remove("dragover");
  });
  els.coverDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    els.coverDropZone.classList.remove("dragover");
    const file = e.dataTransfer.files?.[0];
    if (file) handleCoverUpload(file);
  });
  els.coverDropZone.addEventListener("click", () => {
    els.coverFile.click();
  });

  // 隐写拆封流程
  async function handleExtract(file) {
    if (!file) return;
    els.extractHint.textContent = `正在解构拆封 ${file.name}...`;
    try {
      const password = els.extractPassword.value.trim();
      await apiPost("extract/prepare", { password });
      const res = await bridge.upload("extract", file, { password });
      const data = unwrap(res);

      if (data?.image) {
        const url = dataUrl(data.image);
        els.extractPreviewImg.src = url;
        els.extractResultPanel.hidden = false;
        els.extractHint.textContent = "拆封成功，已成功还原生成原图！";
        showToast("隐写原图还原成功！");

        els.btnDownloadExtracted.onclick = () => {
          const link = document.createElement("a");
          link.href = url;
          link.download = data.name || "extracted_masterpiece.png";
          link.click();
        };
      }
    } catch (err) {
      els.extractHint.textContent = `拆封失败: ${errorMessage(err)}`;
      showToast(`拆封失败: ${errorMessage(err)}`, "error");
    }
  }

  els.extractFile.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) handleExtract(file);
    e.target.value = "";
  });

  els.extractDropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    els.extractDropZone.classList.add("dragover");
  });
  els.extractDropZone.addEventListener("dragleave", () => {
    els.extractDropZone.classList.remove("dragover");
  });
  els.extractDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    els.extractDropZone.classList.remove("dragover");
    const file = e.dataTransfer.files?.[0];
    if (file) handleExtract(file);
  });
}

function startStudio() {
  try {
    setupEventListeners();
  } catch (err) {
    showToast(`交互绑定失败: ${errorMessage(err)}`, "error");
  }
  bootstrap();
}

// 经典脚本放在 </body> 前时 DOM 已解析；模块脚本则可能错过 DOMContentLoaded。
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startStudio);
} else {
  startStudio();
}
