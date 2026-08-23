/**
 * 绘台 (Studio) - 极简实用主义驱动脚本
 * 原生现代 ESM 架构，零外部依赖，极速毫秒级响应
 */

// 示例画面库
const SAMPLES = [
  "1girl, 长发, 白发, 夜景旗袍, 侧光, 看着镜头, 高清",
  "1girl, 汉服, 折扇, 唯美, 黑发, 红色眼瞳, 高画质",
  "1girl, 赛博机能风, 机械义肢, 荧光眼眸, 霓虹光影",
  "1girl, 水彩风格, 夏日微风, JK制服, 向日葵",
  "1girl, 洛丽塔洋装, 玫瑰, 哥特风格, 暗调光影",
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
        default_preset: "laowuyang",
        default_size: "832x1216",
        allow_nsfw: false,
        enable_face_variation: true,
        presets: [
          { number: 0, key: "none", label: "无预设", faces: 0 },
          { number: 1, key: "laowuyang", label: "老五样", faces: 16 },
          { number: 2, key: "hiten", label: "hiten", faces: 16 },
          { number: 3, key: "pop", label: "波普撞色", faces: 16 },
          { number: 4, key: "ghostblade", label: "鬼刀厚涂", faces: 12 },
          { number: 5, key: "mature", label: "成熟妩媚", faces: 16 },
          { number: 6, key: "watercolor", label: "水彩透明", faces: 12 },
          { number: 7, key: "retro", label: "复古赛璐璐", faces: 12 },
          { number: 8, key: "oil", label: "厚涂油画", faces: 12 },
        ],
        sizes: [
          { key: "832x1216", label: "竖图", hint: "832×1216" },
          { key: "832x832", label: "方图", hint: "832×832" },
          { key: "1216x832", label: "横图", hint: "1216×832" },
          { key: "1024x1024", label: "大图", hint: "1024×1024" },
        ],
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

// 全局状态
const state = {
  configured: false,
  preset: "laowuyang",
  size: "832x1216",
  currentName: "",
  stegoName: "",
  presets: [],
  sizes: [],
  gallery: [],
  covers: [],
  thumbs: new Map(),
  isBusy: false,
};

// DOM 元素引用
const els = {
  // 顶栏
  apiStatus: document.getElementById("status-api"),
  statusDot: document.getElementById("status-dot"),
  modelStatus: document.getElementById("status-model"),
  galleryCount: document.getElementById("status-gallery"),
  coverCount: document.getElementById("status-covers"),
  tabGalleryCount: document.getElementById("tab-gallery-count"),
  tabCoverCount: document.getElementById("tab-cover-count"),
  
  // 表单与输入
  form: document.getElementById("draw-form"),
  prompt: document.getElementById("prompt"),
  btnClearPrompt: document.getElementById("btn-clear-prompt"),
  btnRandomPrompt: document.getElementById("btn-random-prompt"),
  artists: document.getElementById("artists"),
  artistChips: document.querySelectorAll(".shortcut-tag"),
  nsfw: document.getElementById("nsfw"),
  face: document.getElementById("face"),
  stego: document.getElementById("stego"),
  stegoPasswordField: document.getElementById("stego-password-field"),
  stegoPassword: document.getElementById("stego-password"),
  drawButton: document.getElementById("draw-button"),
  drawSpinner: document.getElementById("draw-spinner"),
  drawBtnText: document.getElementById("draw-btn-text"),
  formHint: document.getElementById("form-hint"),
  presetGrid: document.getElementById("preset-grid"),
  sizeRow: document.getElementById("size-row"),
  presetSummary: document.getElementById("preset-summary"),
  sizeSummary: document.getElementById("size-summary"),

  // 画布与结果区
  canvasViewport: document.getElementById("canvas-viewport"),
  artworkFrame: document.getElementById("artwork-frame"),
  resultImage: document.getElementById("result-image"),
  resultEmpty: document.getElementById("result-empty"),
  resultDock: document.getElementById("result-dock"),
  downloadResult: document.getElementById("download-result"),
  downloadStego: document.getElementById("download-stego"),
  sheetPreset: document.getElementById("sheet-preset"),
  sheetSize: document.getElementById("sheet-size"),
  sheetNsfw: document.getElementById("sheet-nsfw"),
  sheetFace: document.getElementById("sheet-face"),
  sheetPrompt: document.getElementById("sheet-prompt"),
  sheetNegative: document.getElementById("sheet-negative"),
  resultNote: document.getElementById("result-note"),
  btnCopyPrompt: document.getElementById("btn-copy-prompt"),
  btnCopyNegative: document.getElementById("btn-copy-negative"),

  // 导航
  tabs: document.querySelectorAll(".nav-tab"),
  tabPanels: document.querySelectorAll(".view-tab-pane"),
  btnToggleTheme: document.getElementById("btn-toggle-theme"),

  // 画廊与载体
  gallery: document.getElementById("gallery"),
  btnRefreshGallery: document.getElementById("btn-refresh-gallery"),
  covers: document.getElementById("covers"),
  coverFile: document.getElementById("cover-file"),
  coverDropZone: document.getElementById("cover-drop-zone"),

  // 隐写提取
  extractDropZone: document.getElementById("extract-drop-zone"),
  extractFile: document.getElementById("extract-file"),
  extractPassword: document.getElementById("extract-password"),
  extractHint: document.getElementById("extract-hint"),
  extractResultPanel: document.getElementById("extract-result-panel"),
  extractPreviewImg: document.getElementById("extract-preview-img"),
  btnDownloadExtracted: document.getElementById("btn-download-extracted"),

  // Toast
  toast: document.getElementById("toast"),
};

function unwrap(payload) {
  if (payload && typeof payload === "object" && payload.status === "ok" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

function errorMessage(error) {
  if (!error) return "请求遇到异常";
  if (typeof error === "string") return error;
  return error.message || "请求遇到异常";
}

function showToast(message, kind = "info") {
  if (!els.toast) return;
  els.toast.hidden = false;
  els.toast.className = `simple-toast ${kind === "error" ? "error" : ""}`.trim();
  els.toast.textContent = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 3500);
}

function setBusy(busy) {
  state.isBusy = busy;
  els.drawButton.disabled = busy;
  els.drawSpinner.hidden = !busy;
  if (els.drawBtnText) els.drawBtnText.textContent = busy ? "正在生成..." : "生成图片";
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

// 选项卡切换
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

// 渲染预设选择器
function renderPresets(presets) {
  els.presetGrid.replaceChildren();
  for (const item of presets) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `choice-btn ${item.key === state.preset ? "active" : ""}`;
    btn.dataset.key = item.key;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", item.key === state.preset ? "true" : "false");

    const nameSpan = document.createElement("span");
    nameSpan.className = "choice-name";
    nameSpan.textContent = item.label.split("（")[0];
    btn.title = item.label;

    const subSpan = document.createElement("span");
    subSpan.className = "choice-sub";
    subSpan.textContent = `#${item.number}`;

    btn.appendChild(nameSpan);
    btn.appendChild(subSpan);

    btn.addEventListener("click", () => {
      state.preset = item.key;
      els.presetSummary.textContent = item.label;
      els.presetGrid.querySelectorAll(".choice-btn").forEach((c) => {
        const isMatch = c.dataset.key === item.key;
        c.classList.toggle("active", isMatch);
        c.setAttribute("aria-checked", isMatch ? "true" : "false");
      });
    });

    els.presetGrid.appendChild(btn);
  }
}

// 渲染画幅尺寸选择器
function renderSizes(sizes) {
  els.sizeRow.replaceChildren();
  for (const item of sizes) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `choice-btn ${item.key === state.size ? "active" : ""}`;
    btn.dataset.key = item.key;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", item.key === state.size ? "true" : "false");

    const nameSpan = document.createElement("span");
    nameSpan.className = "choice-name";
    nameSpan.textContent = item.label;

    const subSpan = document.createElement("span");
    subSpan.className = "choice-sub";
    subSpan.textContent = item.hint;

    btn.appendChild(nameSpan);
    btn.appendChild(subSpan);

    btn.addEventListener("click", () => {
      state.size = item.key;
      els.sizeSummary.textContent = `${item.label} (${item.hint})`;
      els.sizeRow.querySelectorAll(".choice-btn").forEach((c) => {
        const isMatch = c.dataset.key === item.key;
        c.classList.toggle("active", isMatch);
        c.setAttribute("aria-checked", isMatch ? "true" : "false");
      });
    });

    els.sizeRow.appendChild(btn);
  }
}

// 渲染画廊
function renderGallery(items) {
  state.gallery = items || [];
  const count = state.gallery.length;
  if (els.galleryCount) els.galleryCount.textContent = count;
  if (els.tabGalleryCount) els.tabGalleryCount.textContent = count;

  els.gallery.replaceChildren();
  if (count === 0) {
    const emptyNotice = document.createElement("p");
    emptyNotice.className = "dropzone-hint";
    emptyNotice.textContent = "暂无生成记录。";
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

    card.addEventListener("click", async () => {
      try {
        const res = await apiGet("preview", { name: item.name });
        if (res?.image) {
          state.currentName = item.name;
          state.stegoName = "";
          displayResultOnCanvas(res.image, {
            preset_label: item.preset || "历史作品",
            size: "自适应",
            nsfw: false,
            face_variation: true,
            prompt: "（历史作品提示词已归档）",
            negative: "—",
          });
          els.tabs[0].click();
          showToast(`已载入 ${item.name}`);
        }
      } catch (err) {
        showToast(`载入失败: ${errorMessage(err)}`, "error");
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
    emptyNotice.className = "dropzone-hint";
    emptyNotice.textContent = "图库暂无图片。";
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
      if (!confirm(`确定删除 ${item.name} 吗？`)) return;
      try {
        const res = await apiPost("covers/delete", { name: item.name });
        renderCovers(res.covers);
        showToast("已删除载体图片");
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
  els.resultImage.src = dataUrl(imageObj);
  els.artworkFrame.hidden = false;
  if (els.resultEmpty) {
    els.resultEmpty.hidden = true;
    els.resultEmpty.style.display = "none";
  }
  els.resultDock.hidden = false;

  els.sheetPreset.textContent = meta.preset_label || meta.preset || "—";
  els.sheetSize.textContent = meta.size || "—";
  els.sheetNsfw.textContent = meta.nsfw ? "NSFW" : "SFW";
  els.sheetFace.textContent = meta.face_variation ? "自动脸型" : "原脸型";
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

// 初始化
async function bootstrap() {
  try {
    const readyState = await bridge.ready();
    if (readyState && readyState.isDark !== undefined) {
      document.documentElement.setAttribute("data-theme", readyState.isDark ? "dark" : "light");
    }

    const data = await apiGet("bootstrap");
    state.configured = Boolean(data.configured);
    state.preset = data.default_preset || "laowuyang";
    state.size = data.default_size || "832x1216";
    state.presets = data.presets || [];
    state.sizes = data.sizes || [];

    els.apiStatus.textContent = state.configured ? "就绪" : "未配置";
    els.statusDot.className = `status-dot ${state.configured ? "ready" : "error"}`;
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
    els.apiStatus.textContent = "离线";
    els.statusDot.className = "status-dot error";
    showToast(`连接失败: ${errorMessage(err)}`, "error");
  }
}

// 事件绑定
function setupEventListeners() {
  setupTabs();

  // 清空描述
  els.btnClearPrompt.addEventListener("click", () => {
    els.prompt.value = "";
    els.prompt.focus();
  });

  // 随机示例
  if (els.btnRandomPrompt) {
    els.btnRandomPrompt.addEventListener("click", () => {
      const idx = Math.floor(Math.random() * SAMPLES.length);
      els.prompt.value = SAMPLES[idx];
      els.prompt.focus();
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
    });
  });

  // 快捷出图：Ctrl + Enter / Cmd + Enter
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
      showToast("已复制正面标签");
    } catch {
      showToast("复制失败", "error");
    }
  });

  els.btnCopyNegative.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(els.sheetNegative.textContent);
      showToast("已复制负面标签");
    } catch {
      showToast("复制失败", "error");
    }
  });

  // 提交出图表单
  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.isBusy) return;

    const promptVal = els.prompt.value.trim();
    if (!promptVal) {
      showToast("请填写画面描述", "error");
      els.prompt.focus();
      return;
    }

    setBusy(true);
    els.formHint.textContent = "正在生成中...";

    try {
      const payload = {
        prompt: promptVal,
        preset: state.preset,
        size: state.size,
        artists: els.artists.value.trim(),
        nsfw: els.nsfw.checked,
        face_variation: els.face.checked,
        stego: els.stego.checked,
        stego_password: els.stegoPassword.value.trim(),
      };

      const result = await apiPost("generate", payload);
      state.currentName = result.name;
      state.stegoName = result.stego?.ok ? result.stego.name : "";

      if (result.image) {
        displayResultOnCanvas(result.image, result);
        state.thumbs.set(result.name, dataUrl(result.image));
      }

      if (result.gallery) {
        renderGallery(result.gallery);
      }

      els.tabs[0].click();
      showToast("出图完成");
    } catch (err) {
      showToast(`生成失败: ${errorMessage(err)}`, "error");
    } finally {
      setBusy(false);
      els.formHint.textContent = "中文会自动转为英文标签";
    }
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
      showToast("已刷新");
    } catch (err) {
      showToast(`刷新失败: ${errorMessage(err)}`, "error");
    }
  });

  // 上传载体
  async function handleCoverUpload(file) {
    if (!file) return;
    try {
      showToast(`正在上传 ${file.name}...`);
      const res = await bridge.upload("covers/upload", file, {});
      const data = unwrap(res);
      renderCovers(data.covers);
      showToast("上传成功");
    } catch (err) {
      showToast(`上传失败: ${errorMessage(err)}`, "error");
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
    els.extractHint.textContent = `正在提取 ${file.name}...`;
    try {
      const password = els.extractPassword.value.trim();
      await apiPost("extract/prepare", { password });
      const res = await bridge.upload("extract", file, { password });
      const data = unwrap(res);

      if (data?.image) {
        const url = dataUrl(data.image);
        els.extractPreviewImg.src = url;
        els.extractResultPanel.hidden = false;
        els.extractHint.textContent = "提取成功";
        showToast("提取成功");

        els.btnDownloadExtracted.onclick = () => {
          const link = document.createElement("a");
          link.href = url;
          link.download = data.name || "extracted.png";
          link.click();
        };
      }
    } catch (err) {
      els.extractHint.textContent = `提取失败: ${errorMessage(err)}`;
      showToast(`提取失败: ${errorMessage(err)}`, "error");
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

// 启动
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  bootstrap();
});
