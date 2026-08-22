function createFallbackBridge() {
  const message = "请在 AstrBot 插件详情页打开暗房";
  const fail = async () => {
    throw new Error(message);
  };
  return {
    ready: async () => ({ isDark: false, pageTitle: "暗房" }),
    apiGet: async (endpoint) => {
      if (endpoint !== "bootstrap") {
        throw new Error(message);
      }
      return {
        configured: false,
        model: "nai-diffusion-4-5-full",
        default_preset: "laowuyang",
        default_size: "832x1216",
        allow_nsfw: false,
        enable_face_variation: true,
        presets: [
          { number: 0, key: "none", label: "无预设", faces: 0 },
          { number: 1, key: "laowuyang", label: "老五样（通用美脸）", faces: 16 },
          { number: 2, key: "hiten", label: "hiten 柔和日系", faces: 16 },
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

const state = {
  configured: false,
  preset: "laowuyang",
  size: "832x1216",
  currentName: "",
  stegoName: "",
  thumbs: new Map(),
};

const els = {
  api: document.getElementById("status-api"),
  model: document.getElementById("status-model"),
  galleryCount: document.getElementById("status-gallery"),
  coverCount: document.getElementById("status-covers"),
  form: document.getElementById("draw-form"),
  prompt: document.getElementById("prompt"),
  artists: document.getElementById("artists"),
  nsfw: document.getElementById("nsfw"),
  face: document.getElementById("face"),
  stego: document.getElementById("stego"),
  stegoPasswordField: document.getElementById("stego-password-field"),
  stegoPassword: document.getElementById("stego-password"),
  drawButton: document.getElementById("draw-button"),
  formHint: document.getElementById("form-hint"),
  presetGrid: document.getElementById("preset-grid"),
  sizeRow: document.getElementById("size-row"),
  lightboxMeta: document.getElementById("lightbox-meta"),
  resultImage: document.getElementById("result-image"),
  resultEmpty: document.getElementById("result-empty"),
  resultSheet: document.getElementById("result-sheet"),
  sheetPreset: document.getElementById("sheet-preset"),
  sheetSize: document.getElementById("sheet-size"),
  sheetNsfw: document.getElementById("sheet-nsfw"),
  sheetFace: document.getElementById("sheet-face"),
  sheetPrompt: document.getElementById("sheet-prompt"),
  sheetNegative: document.getElementById("sheet-negative"),
  resultNote: document.getElementById("result-note"),
  downloadResult: document.getElementById("download-result"),
  downloadStego: document.getElementById("download-stego"),
  gallery: document.getElementById("gallery"),
  covers: document.getElementById("covers"),
  coverFile: document.getElementById("cover-file"),
  coverHint: document.getElementById("cover-hint"),
  extractFile: document.getElementById("extract-file"),
  extractPassword: document.getElementById("extract-password"),
  extractHint: document.getElementById("extract-hint"),
  toast: document.getElementById("toast"),
};

function unwrap(payload) {
  if (payload && typeof payload === "object" && payload.status === "ok" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

function errorMessage(error) {
  if (!error) return "请求失败";
  if (typeof error === "string") return error;
  return error.message || "请求失败";
}

function showToast(message, kind = "info") {
  els.toast.hidden = false;
  els.toast.className = `toast ${kind === "error" ? "error" : ""}`.trim();
  els.toast.textContent = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 4200);
}

function setBusy(busy) {
  document.body.classList.toggle("busy", busy);
  els.drawButton.disabled = busy;
}

function dataUrl(image) {
  return `data:${image.mime || "image/png"};base64,${image.data}`;
}

function rememberThumb(item, image) {
  if (item?.name && image?.data) {
    state.thumbs.set(item.name, dataUrl(image));
  }
}

async function apiGet(endpoint, params) {
  return unwrap(await bridge.apiGet(endpoint, params));
}

async function apiPost(endpoint, body) {
  return unwrap(await bridge.apiPost(endpoint, body));
}

function renderChoices(container, items, selected, onPick, labelKey = "label") {
  const legend = container.querySelector("legend");
  container.replaceChildren(legend);
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice";
    button.dataset.key = item.key;
    button.setAttribute("aria-pressed", String(item.key === selected));
    button.innerHTML = `<strong>${item[labelKey]}</strong><small>${item.hint || item.key}</small>`;
    button.addEventListener("click", () => onPick(item.key));
    container.append(button);
  }
}

function renderPresets(presets, selected) {
  renderChoices(
    els.presetGrid,
    presets.map((item) => ({
      key: item.key,
      label: `${item.number} ${item.label}`,
      hint: item.faces ? `${item.faces} 种脸型` : "无预设",
    })),
    selected,
    (key) => {
      state.preset = key;
      renderPresets(presets, key);
    },
  );
}

function renderSizes(sizes, selected) {
  renderChoices(els.sizeRow, sizes, selected, (key) => {
    state.size = key;
    renderSizes(sizes, key);
  });
}

function renderThumbList(container, items, emptyText, onOpen, onDelete) {
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "thumb";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "thumb-open";
    const img = document.createElement("img");
    img.alt = item.name;
    const cached = state.thumbs.get(item.name);
    if (cached) {
      img.src = cached;
    } else {
      img.hidden = true;
    }
    const caption = document.createElement("span");
    caption.textContent = item.preset ? `${item.preset} · ${item.name}` : item.name;
    open.append(img, caption);
    open.addEventListener("click", () => onOpen(item));
    card.append(open);
    if (onDelete) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost thumb-delete";
      remove.textContent = "删除";
      remove.addEventListener("click", () => onDelete(item));
      card.append(remove);
    }
    container.append(card);
    if (!cached) {
      loadThumb(item, img);
    }
  }
}

async function loadThumb(item, img) {
  try {
    const result = await apiGet("preview", { name: item.name });
    if (!result?.image) return;
    rememberThumb(item, result.image);
    img.src = dataUrl(result.image);
    img.hidden = false;
  } catch (error) {
    img.hidden = true;
  }
}

function showResult(payload) {
  const image = payload.image;
  if (!image) return;
  state.currentName = payload.name || image.name;
  state.stegoName = payload.stego?.ok ? payload.stego.name : "";
  els.resultImage.src = dataUrl(image);
  els.resultImage.hidden = false;
  els.resultEmpty.hidden = true;
  els.resultSheet.hidden = false;
  els.sheetPreset.textContent = payload.preset_label
    ? `${payload.preset_number} = ${payload.preset_label}`
    : payload.name || "样张";
  els.sheetSize.textContent = payload.size || "—";
  els.sheetNsfw.textContent = payload.nsfw ? "开启" : "关闭";
  els.sheetFace.textContent = payload.face_variation ? "开启" : "关闭";
  els.sheetPrompt.textContent = payload.prompt || "—";
  els.sheetNegative.textContent = payload.negative || "—";
  els.lightboxMeta.textContent = state.currentName;
  els.downloadResult.disabled = !state.currentName;
  els.downloadStego.hidden = !state.stegoName;
  if (payload.note) {
    els.resultNote.hidden = false;
    els.resultNote.textContent = payload.note;
  } else if (payload.stego && payload.stego.ok === false) {
    els.resultNote.hidden = false;
    els.resultNote.textContent = payload.stego.message;
  } else {
    els.resultNote.hidden = true;
  }
  rememberThumb({ name: state.currentName }, image);
}

function applyBootstrap(data) {
  state.configured = Boolean(data.configured);
  state.preset = data.default_preset || "laowuyang";
  state.size = data.default_size || "832x1216";
  els.api.textContent = data.configured ? "已接通" : "未配置";
  els.model.textContent = data.model || "—";
  els.nsfw.checked = Boolean(data.allow_nsfw);
  els.face.checked = data.enable_face_variation !== false;
  els.formHint.textContent = data.configured
    ? "中文会先转成标签，再送进 NAI 4.5。"
    : "先在管理面板填写 API 地址和密钥，暗房才能出片。";
  renderPresets(data.presets || [], state.preset);
  renderSizes(data.sizes || [], state.size);
  renderGallery(data.gallery || []);
  renderCovers(data.covers || []);
}

function renderGallery(items) {
  els.galleryCount.textContent = String(items.length);
  renderThumbList(els.gallery, items, "还没有样张。", async (item) => {
    try {
      const result = await apiGet("preview", { name: item.name });
      showResult({
        name: item.name,
        preset: item.preset,
        preset_label: item.preset,
        size: "",
        image: result.image,
      });
    } catch (error) {
      showToast(errorMessage(error), "error");
    }
  });
}

function renderCovers(items) {
  els.coverCount.textContent = String(items.length);
  renderThumbList(
    els.covers,
    items,
    "载体柜是空的。隐写前先加几张图。",
    async (item) => {
      try {
        const result = await apiGet("preview", { name: item.name });
        showResult({
          name: item.name,
          preset_label: "载体",
          image: result.image,
        });
      } catch (error) {
        showToast(errorMessage(error), "error");
      }
    },
    async (item) => {
      try {
        const result = await apiPost("covers/delete", { name: item.name });
        renderCovers(result.covers || []);
        showToast(`已移出载体：${item.name}`);
      } catch (error) {
        showToast(errorMessage(error), "error");
      }
    },
  );
}

async function downloadNamed(name) {
  if (!name) return;
  await bridge.download("download", { name }, name);
}

els.stego.addEventListener("change", () => {
  els.stegoPasswordField.hidden = !els.stego.checked;
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!els.prompt.value.trim()) {
    showToast("请填写画面描述。", "error");
    return;
  }
  setBusy(true);
  els.lightboxMeta.textContent = "暗房正在冲洗…";
  try {
    const result = await apiPost("generate", {
      prompt: els.prompt.value,
      preset: state.preset,
      size: state.size,
      artists: els.artists.value,
      nsfw: els.nsfw.checked,
      face_variation: els.face.checked,
      stego: els.stego.checked,
      stego_password: els.stegoPassword.value,
    });
    showResult(result);
    renderGallery(result.gallery || []);
    showToast(result.stego?.ok ? "样张已写入载体。" : "样张已出灯箱。");
  } catch (error) {
    showToast(errorMessage(error), "error");
    els.lightboxMeta.textContent = "冲洗失败，检查描述或上游配置。";
  } finally {
    setBusy(false);
  }
});

els.downloadResult.addEventListener("click", () => downloadNamed(state.currentName));
els.downloadStego.addEventListener("click", () => downloadNamed(state.stegoName));

els.coverFile.addEventListener("change", async () => {
  const file = els.coverFile.files?.[0];
  if (!file) return;
  try {
    const result = unwrap(await bridge.upload("covers/upload", file));
    renderCovers(result.covers || []);
    els.coverHint.textContent = `已加入 ${result.name}`;
    showToast("载体已入柜。");
  } catch (error) {
    showToast(errorMessage(error), "error");
  } finally {
    els.coverFile.value = "";
  }
});

els.extractFile.addEventListener("change", async () => {
  const file = els.extractFile.files?.[0];
  if (!file) return;
  try {
    await apiPost("extract/prepare", { password: els.extractPassword.value });
    const result = unwrap(await bridge.upload("extract", file));
    showResult({
      name: result.image?.name,
      preset_label: "拆封结果",
      image: result.image,
    });
    els.extractHint.textContent = "已从原始 PNG 拆出生成图。";
    showToast("拆封完成。");
  } catch (error) {
    showToast(errorMessage(error), "error");
    els.extractHint.textContent = errorMessage(error);
  } finally {
    els.extractFile.value = "";
  }
});

async function boot() {
  await bridge.ready();
  try {
    applyBootstrap(await apiGet("bootstrap"));
  } catch (error) {
    els.api.textContent = "桥接失败";
    showToast(errorMessage(error), "error");
  }
}

boot();
