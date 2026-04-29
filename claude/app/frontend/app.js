const { createApp, reactive, ref, computed, onMounted, watch, nextTick } = Vue;

const API = "";
const STORAGE_KEYS = {
  theme: "bk-theme",
  presets: "bk-saved-presets",
  lastForm: "bk-last-form",
  ui: "bk-ui-settings",
};

const PALETTE = [
  "#4d63d1", "#2f8f4e", "#c08a2a", "#c64338", "#7c3aed",
  "#0891b2", "#be185d", "#0d9488", "#a16207", "#374151",
];

const PALETTE_SOFT = [
  "#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#0f766e",
  "#9333ea", "#0891b2", "#be123c", "#64748b", "#ca8a04",
];

const DEFAULT_PERIOD = {
  type: "range",
  date: "2025-12-31",
  date_from: "2025-01-01",
  date_to: "2025-12-31",
  date_a: "2025-01-01",
  date_b: "2025-12-31",
};

const DEFAULT_UI = {
  fontSize: "normal",
  bg: "default",
  accent: "blue",
  sidebar: "left",
  chartStyle: "classic",
};

const QUICK_QUESTIONS = [
  "Где самое низкое исполнение?",
  "Где есть лимит, но нет кассы?",
  "Где БО больше лимита?",
  "Какие объекты требуют внимания?",
  "Покажи объекты с высоким риском",
  "Где контракты меньше лимита?",
  "Какие документы связаны с детским садом?",
  "Найди объект по КЦСР или КВР",
];

const TOUR_STEPS = [
  { target: "guide", title: "Краткий сценарий", text: "Начните с поиска или быстрых вопросов. Приложение подберет объект, показатели и покажет аналитику." },
  { target: "smart-search", title: "Глобальный поиск", text: "Ищет по объектам, мероприятиям, КЦСР, КВР, контрагентам и номерам документов. Можно диктовать запрос голосом." },
  { target: "filters", title: "Конструктор выборки", text: "Здесь задаются раздел, объекты, показатели и период. По умолчанию период стоит с 01.01.2025 по 31.12.2025." },
  { target: "actions", title: "Построение отчета", text: "Постройте выборку вручную или нажмите быстрый отчет: система включит ключевые показатели, риски и Excel." },
  { target: "settings", title: "Внешний вид", text: "В шестеренке можно менять размер шрифта, фон, акцент, сторону панели и стиль диаграмм." },
];

const SOURCE_SHORT = {
  planning:    "РЧБ",
  agreements:  "Согл.",
  procurement: "ГЗ",
  buau:        "БУ/АУ",
  computed:    "расч.",
  derived:     "расч.",
};

createApp({
  setup() {
    /* ─── State ─────────────────────────────── */
    const health = ref(null);
    const objectTypes = ref([]);
    const sections = ref([]);
    const metrics = ref([]);
    const presets = ref({});

    const objects = ref([]);
    const objectsCache = ref({});  // id -> obj (нужен для чипов в "выбрано")

    const loadingObjects = ref(false);
    const loadingResult = ref(false);
    const reloading = ref(false);

    const result = ref(null);
    const tab = ref("summary");

    const theme = ref(localStorage.getItem(STORAGE_KEYS.theme) || "light");
    const settingsOpen = ref(false);
    const ui = reactive(loadUiSettings());
    const savedPresets = ref(loadSavedPresetsFromStorage());

    const toasts = ref([]);
    let toastSeq = 0;

    const smartQuery = ref("");
    const smartResults = ref([]);
    const smartLoading = ref(false);
    const voiceActive = ref(false);
    const quickQuestions = ref(shuffle(QUICK_QUESTIONS).slice(0, 4));
    const expandedObjects = ref({});
    const expandedSummary = ref({});
    const tourOpen = ref(false);
    const tourIndex = ref(0);
    const chatOpen = ref(false);

    const form = reactive({
      section: null,
      types: [],
      query: "",
      objects: [],
      metrics: [],
      period: { ...DEFAULT_PERIOD },
    });

    const chartCanvas = ref(null);
    const barCanvas = ref(null);
    let lineChart = null;
    let barChart = null;

    /* ─── Init ──────────────────────────────── */
    applyTheme(theme.value);
    applyUiSettings();

    let searchTimer = null;
    function onSearchInput() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(reloadObjects, 300);
    }
    function clearQuery() {
      form.query = "";
      reloadObjects();
    }

    let smartTimer = null;
    function onSmartInput() {
      clearTimeout(smartTimer);
      smartTimer = setTimeout(runSmartSearch, 260);
    }

    async function runSmartSearch() {
      const q = smartQuery.value.trim();
      if (!q) {
        smartResults.value = [];
        return;
      }
      smartLoading.value = true;
      try {
        const params = new URLSearchParams({ q, limit: "6" });
        if (form.section) params.set("section", form.section);
        const r = await fetchJSON(`${API}/api/objects?${params.toString()}`);
        smartResults.value = r.items || [];
      } catch (e) {
        pushToast("Глобальный поиск не сработал: " + e.message, "error");
      } finally {
        smartLoading.value = false;
      }
    }

    function clearSmartSearch() {
      smartQuery.value = "";
      smartResults.value = [];
    }

    async function selectSmartResult(obj, build = false) {
      if (!obj) return;
      objectsCache.value[obj.id] = obj;
      if (!form.objects.includes(obj.id)) form.objects = [obj.id];
      form.query = obj.name;
      smartQuery.value = obj.name;
      await reloadObjects();
      if (build) await buildSelection();
    }

    async function submitSmartSearch() {
      if (!smartResults.value.length) await runSmartSearch();
      if (smartResults.value.length) {
        await selectSmartResult(smartResults.value[0], false);
        pushToast("Объект найден и выбран. Можно строить выборку.", "ok");
      } else if (smartQuery.value.trim()) {
        form.query = smartQuery.value.trim();
        await reloadObjects();
      }
    }

    function useQuickQuestion(q) {
      smartQuery.value = q;
      if (/низкое|вниман|риск|лимит|касс|БО|контракт/i.test(q)) {
        applyPreset("full");
        form.period = { ...form.period, ...DEFAULT_PERIOD, type: "range" };
        pushToast("Включил полный срез. Постройте выборку, чтобы увидеть ответ.", "ok");
      }
      runSmartSearch();
    }

    async function startVoiceInput() {
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Recognition) {
        pushToast("Голосовой ввод недоступен в этом браузере", "error");
        return;
      }
      const rec = new Recognition();
      rec.lang = "ru-RU";
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      voiceActive.value = true;
      rec.onresult = (event) => {
        const text = event.results?.[0]?.[0]?.transcript || "";
        smartQuery.value = text;
        form.query = text;
        runSmartSearch();
      };
      rec.onerror = () => pushToast("Не удалось распознать голосовой запрос", "error");
      rec.onend = () => { voiceActive.value = false; };
      rec.start();
    }

    async function fetchJSON(url, options) {
      const res = await fetch(url, options);
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body && body.detail) detail = String(body.detail);
        } catch (_) { /* ignore */ }
        throw new Error(detail);
      }
      return res.json();
    }

    async function loadInitial() {
      try {
        health.value = await fetchJSON(`${API}/api/health`);
      } catch (e) {
        console.error("health", e);
        pushToast("Не удалось получить статус сервера: " + e.message, "error");
      }
      try {
        const m = await fetchJSON(`${API}/api/metrics`);
        metrics.value = m.metrics || [];
        presets.value = m.presets || {};
      } catch (e) {
        pushToast("Не удалось загрузить каталог показателей", "error");
      }
      try {
        const s = await fetchJSON(`${API}/api/sections`);
        sections.value = s.sections || [];
      } catch (e) { /* not critical */ }
      try {
        const t = await fetchJSON(`${API}/api/object_types`);
        objectTypes.value = t.items || [];
      } catch (e) { /* not critical */ }
      restoreLastForm();
      await reloadObjects();
    }

    async function reloadObjects() {
      loadingObjects.value = true;
      try {
        const params = new URLSearchParams();
        if (form.query) params.set("q", form.query);
        if (form.section) params.set("section", form.section);
        if (form.types.length) params.set("types", form.types.join(","));
        params.set("limit", "200");
        const r = await fetchJSON(`${API}/api/objects?${params.toString()}`);
        objects.value = r.items || [];
        for (const o of objects.value) objectsCache.value[o.id] = o;
      } catch (e) {
        console.error(e);
        pushToast("Поиск объектов не удался: " + e.message, "error");
      } finally {
        loadingObjects.value = false;
      }
    }

    /* ─── Form actions ──────────────────────── */
    function toggleType(id) {
      const i = form.types.indexOf(id);
      if (i >= 0) form.types.splice(i, 1);
      else form.types.push(id);
      reloadObjects();
    }
    function toggleMetric(code) {
      const i = form.metrics.indexOf(code);
      if (i >= 0) form.metrics.splice(i, 1);
      else form.metrics.push(code);
    }
    function removeObject(id) {
      const i = form.objects.indexOf(id);
      if (i >= 0) form.objects.splice(i, 1);
    }

    function applyPreset(key) {
      const p = presets.value[key];
      if (!p) return;
      form.metrics = [...p.metrics];
      pushToast(`Пресет «${p.title}» применён (${p.metrics.length} показателей)`, "ok");
    }

    function isPresetActive(key) {
      const p = presets.value[key];
      if (!p) return false;
      const a = new Set(form.metrics);
      const b = new Set(p.metrics);
      if (a.size !== b.size) return false;
      for (const x of a) if (!b.has(x)) return false;
      return true;
    }

    function resetForm() {
      form.section = null;
      form.types = [];
      form.query = "";
      form.objects = [];
      form.metrics = [];
      form.period = { ...DEFAULT_PERIOD };
      result.value = null;
      expandedSummary.value = {};
      reloadObjects();
      pushToast("Форма сброшена", "ok");
    }

    function buildPayload() {
      return {
        objects: form.objects,
        metrics: form.metrics,
        section: form.section,
        period: form.period,
      };
    }

    async function buildSelection() {
      if (!form.metrics.length) {
        pushToast("Выберите хотя бы один показатель или примените пресет", "error");
        return;
      }
      loadingResult.value = true;
      try {
        const payload = buildPayload();
        const r = await fetchJSON(`${API}/api/selection`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        result.value = r;
        if (!availableTabs.value.find(t => t.id === tab.value)) {
          tab.value = availableTabs.value[0]?.id || "summary";
        }
        saveLastForm();
        await nextTick();
        renderCharts();
        const found = (r.summary || []).length;
        pushToast(found ? `Готово: ${found} объектов` : "По выбранным параметрам данные не найдены", found ? "ok" : "info");
      } catch (e) {
        pushToast("Не удалось построить выборку: " + e.message, "error");
      } finally {
        loadingResult.value = false;
      }
    }

    async function exportExcel(payloadOverride = null) {
      if (!form.metrics.length) {
        pushToast("Сначала постройте выборку", "error");
        return;
      }
      const payload = payloadOverride && Array.isArray(payloadOverride.metrics) ? payloadOverride : buildPayload();
      try {
        const res = await fetch(`${API}/api/export`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            if (body && body.detail) detail = String(body.detail);
          } catch (_) { /* ignore */ }
          throw new Error(detail);
        }
        const blob = await res.blob();
        const cd = res.headers.get("Content-Disposition") || "";
        const m = /filename="?([^";]+)"?/.exec(cd);
        const name = m ? m[1] : "selection.xlsx";
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        a.click();
        URL.revokeObjectURL(url);
        pushToast("Файл Excel сохранён", "ok");
      } catch (e) {
        pushToast("Не удалось сформировать Excel: " + e.message, "error");
      }
    }

    async function buildQuickReport() {
      if (!form.objects.length && smartQuery.value.trim()) {
        await runSmartSearch();
        if (smartResults.value.length) await selectSmartResult(smartResults.value[0], false);
      }
      if (!form.objects.length && objects.value.length) {
        await selectSmartResult(objects.value[0], false);
      }
      if (!form.objects.length) {
        pushToast("Введите или выберите объект для быстрого отчета", "error");
        return;
      }
      const full = presets.value.full?.metrics || metrics.value.map(m => m.code);
      form.metrics = [...full];
      form.period = { ...form.period, ...DEFAULT_PERIOD, type: "range" };
      await buildSelection();
      await exportExcel(buildPayload());
    }

    async function reload() {
      reloading.value = true;
      try {
        const r = await fetchJSON(`${API}/api/reload`, { method: "POST" });
        health.value = await fetchJSON(`${API}/api/health`);
        await reloadObjects();
        pushToast(`Данные перечитаны: ${r.facts || 0} фактов`, "ok");
      } catch (e) {
        pushToast("Перечитать данные не удалось: " + e.message, "error");
      } finally {
        reloading.value = false;
      }
    }

    /* ─── Theme ─────────────────────────────── */
    function applyTheme(t) {
      document.documentElement.setAttribute("data-theme", t);
      localStorage.setItem(STORAGE_KEYS.theme, t);
    }
    function toggleTheme() {
      theme.value = theme.value === "dark" ? "light" : "dark";
      applyTheme(theme.value);
      // Перерисовать графики, если они есть
      nextTick(renderCharts);
    }

    function loadUiSettings() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.ui);
        return raw ? { ...DEFAULT_UI, ...JSON.parse(raw) } : { ...DEFAULT_UI };
      } catch (_) {
        return { ...DEFAULT_UI };
      }
    }

    function applyUiSettings() {
      document.documentElement.setAttribute("data-font", ui.fontSize);
      document.documentElement.setAttribute("data-bg", ui.bg);
      document.documentElement.setAttribute("data-accent", ui.accent);
      document.documentElement.setAttribute("data-chart", ui.chartStyle);
      localStorage.setItem(STORAGE_KEYS.ui, JSON.stringify({ ...ui }));
      nextTick(renderCharts);
    }

    function setUi(key, value) {
      ui[key] = value;
      applyUiSettings();
    }

    /* ─── Saved presets (новая фича) ────────── */
    function loadSavedPresetsFromStorage() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.presets);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr : [];
      } catch (_) { return []; }
    }
    function persistSavedPresets() {
      localStorage.setItem(STORAGE_KEYS.presets, JSON.stringify(savedPresets.value));
    }
    function saveCurrentAsPreset() {
      const name = prompt("Название пресета:", `Пресет ${savedPresets.value.length + 1}`);
      if (!name) return;
      savedPresets.value.push({
        name,
        section: form.section,
        types: [...form.types],
        objects: [...form.objects],
        metrics: [...form.metrics],
        period: { ...form.period },
      });
      persistSavedPresets();
      pushToast(`Пресет «${name}» сохранён`, "ok");
    }
    function loadSavedPreset(p) {
      form.section = p.section ?? null;
      form.types = [...(p.types || [])];
      form.objects = [...(p.objects || [])];
      form.metrics = [...(p.metrics || [])];
      form.period = { ...form.period, ...(p.period || {}) };
      reloadObjects();
      pushToast(`Загружен пресет «${p.name}»`, "ok");
    }
    function deleteSavedPreset(idx) {
      const removed = savedPresets.value.splice(idx, 1)[0];
      persistSavedPresets();
      if (removed) pushToast(`Пресет «${removed.name}» удалён`, "ok");
    }

    /* ─── Last form snapshot ────────────────── */
    function saveLastForm() {
      try {
        localStorage.setItem(STORAGE_KEYS.lastForm, JSON.stringify({
          section: form.section, types: form.types,
          objects: form.objects, metrics: form.metrics,
          period: form.period,
        }));
      } catch (_) {}
    }
    function restoreLastForm() {
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.lastForm);
        if (!raw) return;
        const v = JSON.parse(raw);
        if (v && typeof v === "object") {
          if (v.section !== undefined) form.section = v.section;
          if (Array.isArray(v.types)) form.types = v.types;
          if (Array.isArray(v.objects)) form.objects = v.objects;
          if (Array.isArray(v.metrics)) form.metrics = v.metrics;
          if (v.period && typeof v.period === "object") form.period = { ...DEFAULT_PERIOD, ...v.period };
          if (!form.period.date_a) form.period.date_a = DEFAULT_PERIOD.date_a;
          if (!form.period.date_b) form.period.date_b = DEFAULT_PERIOD.date_b;
          if (!form.period.date_from) form.period.date_from = DEFAULT_PERIOD.date_from;
          if (!form.period.date_to) form.period.date_to = DEFAULT_PERIOD.date_to;
        }
      } catch (_) {}
    }

    /* ─── Toasts ────────────────────────────── */
    function pushToast(text, type = "info") {
      const id = ++toastSeq;
      toasts.value.push({ id, text, type });
      setTimeout(() => dismissToast(id), 4500);
    }
    function dismissToast(id) {
      const i = toasts.value.findIndex(t => t.id === id);
      if (i >= 0) toasts.value.splice(i, 1);
    }

    /* ─── Charts ────────────────────────────── */
    function destroyCharts() {
      if (lineChart) { lineChart.destroy(); lineChart = null; }
      if (barChart)  { barChart.destroy();  barChart = null;  }
    }

    function chartTextColor() {
      const root = getComputedStyle(document.documentElement);
      return root.getPropertyValue("--ink-2").trim() || "#3a3a3d";
    }
    function chartGridColor() {
      const root = getComputedStyle(document.documentElement);
      return root.getPropertyValue("--line").trim() || "#e6e3dc";
    }

    function renderCharts() {
      destroyCharts();
      if (!result.value) return;
      const meta = result.value.metric_meta || [];
      const text = chartTextColor();
      const grid = chartGridColor();

      Chart.defaults.color = text;
      Chart.defaults.borderColor = grid;
      Chart.defaults.font.family = "Inter, system-ui, sans-serif";
      const palette = ui.chartStyle === "soft" ? PALETTE_SOFT : PALETTE;
      const softChart = ui.chartStyle === "soft";

      if (chartCanvas.value && (result.value.dynamic || []).length) {
        const labels = result.value.dynamic.map(d => d.month);
        const datasets = meta.map((m, i) => ({
          label: m.name,
          data: result.value.dynamic.map(d => d[m.code] || 0),
          borderColor: palette[i % palette.length],
          backgroundColor: palette[i % palette.length] + (softChart ? "24" : "22"),
          tension: softChart ? 0.38 : 0.25,
          fill: softChart,
          borderWidth: softChart ? 2.5 : 2,
          pointRadius: softChart ? 2 : 3,
        }));
        lineChart = new Chart(chartCanvas.value, {
          type: "line",
          data: { labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
              legend: { position: "bottom", labels: { color: text } },
              tooltip: {
                callbacks: { label: ctx => `${ctx.dataset.label}: ${formatMoney(ctx.parsed.y)}` },
              },
            },
            scales: {
              x: { grid: { color: grid } },
              y: {
                grid: { color: grid },
                ticks: { callback: v => formatMoneyShort(v) },
              },
            },
          },
        });
      }

      if (barCanvas.value && (result.value.summary || []).length) {
        const top = [...result.value.summary]
          .map(r => ({
            name: r.object,
            total: meta.reduce((s, m) => s + (Number(r[m.code]) || 0), 0),
            row: r,
          }))
          .sort((a, b) => b.total - a.total)
          .slice(0, 12);
        const labels = top.map(t => clip(t.name, 50));
        const datasets = meta.map((m, i) => ({
          label: m.name,
          data: top.map(t => t.row[m.code] || 0),
          backgroundColor: palette[i % palette.length],
          borderRadius: softChart ? 7 : 3,
        }));
        barChart = new Chart(barCanvas.value, {
          type: "bar",
          data: { labels, datasets },
          options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position: "bottom", labels: { color: text } },
              tooltip: {
                callbacks: { label: ctx => `${ctx.dataset.label}: ${formatMoney(ctx.parsed.x)}` },
              },
            },
            scales: {
              x: { grid: { color: grid }, ticks: { callback: v => formatMoneyShort(v) } },
              y: { grid: { color: grid } },
            },
          },
        });
      }
    }

    /* ─── Helpers ───────────────────────────── */
    function clip(s, n) { return (s || "").length > n ? s.slice(0, n - 1) + "…" : s || ""; }
    function queryTokens() {
      return smartQuery.value.toLowerCase().split(/[\s,;:№#"'()]+/).filter(t => t.length >= 2);
    }
    function smartTitle(obj) {
      const name = obj?.name || "";
      const lower = name.toLowerCase();
      const token = queryTokens().find(t => lower.includes(t));
      if (!token) return clip(name, 72);
      const idx = lower.indexOf(token);
      const start = Math.max(0, idx - 32);
      const end = Math.min(name.length, idx + token.length + 46);
      return `${start ? "…" : ""}${name.slice(start, end)}${end < name.length ? "…" : ""}`;
    }
    function smartContext(obj) {
      const parts = [];
      if (obj?.kcsr) parts.push(`КЦСР ${obj.kcsr}`);
      if (obj?.kvr) parts.push(`КВР ${obj.kvr}`);
      if (obj?.dopkr) parts.push(`ДопКР ${obj.dopkr}`);
      return parts.join(" · ") || objectTypeTitle(obj?.type);
    }
    function smartTags(obj) {
      const type = objectTypeTitle(obj?.type);
      return `${type} · ${obj?.facts || 0} зап.`;
    }
    function objectTypeTitle(type) {
      const map = {
        kcsr_event: "мероприятие",
        capital_object: "объект",
        agreement: "соглашение",
        contract_object: "контракт",
        buau_org: "БУ/АУ",
      };
      return map[type] || type || "объект";
    }
    function formatMoney(n) {
      const num = Number(n);
      if (!isFinite(num) || num === 0) return "—";
      return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
    }
    function formatMoneyShort(n) {
      const a = Math.abs(Number(n) || 0);
      if (a === 0) return "—";
      if (a >= 1e9) return (n / 1e9).toFixed(1) + " млрд";
      if (a >= 1e6) return (n / 1e6).toFixed(1) + " млн";
      if (a >= 1e3) return (n / 1e3).toFixed(0) + " тыс";
      return new Intl.NumberFormat("ru-RU").format(n);
    }
    function formatKpi(n) {
      const a = Math.abs(Number(n) || 0);
      if (!isFinite(a) || a === 0) return "—";
      if (a >= 1e9) return (n / 1e9).toFixed(2).replace(".", ",") + " млрд";
      if (a >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " млн";
      if (a >= 1e3) return (n / 1e3).toFixed(0) + " тыс";
      return new Intl.NumberFormat("ru-RU").format(n);
    }
    function formatPct(n) {
      const num = Number(n);
      if (!isFinite(num)) return "—";
      return num.toFixed(1).replace(".", ",") + " %";
    }
    function formatDelta(n) {
      const num = Number(n);
      if (!isFinite(num)) return "—";
      const sign = num >= 0 ? "+" : "−";
      return sign + Math.abs(num).toFixed(1).replace(".", ",") + "%";
    }
    function formatCount(n) {
      const num = Number(n) || 0;
      if (num >= 1e6) return (num / 1e6).toFixed(1) + "M";
      if (num >= 1e3) return (num / 1e3).toFixed(0) + "k";
      return String(num);
    }
    function plural(n, one, few, many) {
      const mod10 = n % 10, mod100 = n % 100;
      if (mod10 === 1 && mod100 !== 11) return one;
      if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
      return many;
    }
    function shortSectionTitle(t) {
      const m = /(КИК|СКК|2\/3|Объекты|ОКВ)/i.exec(t);
      if (m) return m[1] === "Объекты" ? "ОКВ" : m[1];
      return t.replace(/^Раздел\s*\d+\.\s*/i, "").slice(0, 18);
    }
    function sourceShort(s) {
      return SOURCE_SHORT[s] || s || "—";
    }
    function pctColor(p) {
      if (p >= 75 && p <= 100) return "var(--ok)";
      if (p >= 40 && p <= 105) return "var(--warn)";
      return "var(--danger)";
    }
    function shuffle(arr) {
      return [...arr].sort(() => Math.random() - 0.5);
    }
    function riskClass(row) {
      return `risk-${row?.risk_level || "green"}`;
    }
    function riskTitle(row) {
      return row?.risk_label || "Норма";
    }
    function toggleObjectText(id) {
      expandedObjects.value = { ...expandedObjects.value, [id]: !expandedObjects.value[id] };
    }
    function toggleSummaryText(key) {
      expandedSummary.value = { ...expandedSummary.value, [key]: !expandedSummary.value[key] };
    }
    function startTour() {
      tourIndex.value = 0;
      tourOpen.value = true;
    }
    function nextTourStep() {
      if (tourIndex.value >= TOUR_STEPS.length - 1) {
        tourOpen.value = false;
      } else {
        tourIndex.value += 1;
      }
    }
    function closeTour() {
      tourOpen.value = false;
    }

    /* ─── Computed ──────────────────────────── */
    const groupedMetrics = computed(() => {
      const groups = {};
      for (const m of metrics.value) (groups[m.group] ||= []).push(m);
      return groups;
    });

    const kpis = computed(() => {
      if (!result.value) return [];
      const totals = result.value.totals || {};
      const meta = result.value.metric_meta || [];
      const dyn = result.value.dynamic || [];
      // Сравниваем последний доступный месяц с предыдущим — даёт «дельту vs прошлый период».
      const lastTwo = dyn.slice(-2);
      const prev = lastTwo.length === 2 ? lastTwo[0] : null;
      const curr = lastTwo.length ? lastTwo[lastTwo.length - 1] : null;

      const list = meta.map(m => {
        const metric = (metrics.value || []).find(x => x.code === m.code);
        const value = totals[m.code] || 0;
        let delta = null;
        if (prev && curr) {
          const a = Number(prev[m.code]) || 0;
          const b = Number(curr[m.code]) || 0;
          if (a !== 0 || b !== 0) {
            const diff = a === 0 ? 100 : ((b - a) / Math.abs(a)) * 100;
            if (isFinite(diff) && Math.abs(diff) >= 0.05) {
              delta = { value: diff, label: `vs ${prev.month || ""}` };
            }
          }
        }
        return {
          code: m.code,
          name: m.name,
          source: metric?.source || "",
          value,
          delta,
        };
      });
      // Добавим расчётные KPI, если есть
      const sums = result.value.summary || [];
      if (sums.some(r => "exec_pct" in r)) {
        const vals = sums.map(r => Number(r.exec_pct)).filter(v => isFinite(v));
        if (vals.length) {
          const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
          list.push({ code: "exec_pct", name: "% исполнения (средн.)", source: "computed", value: avg, accent: true, pct: true, delta: null });
        }
      }
      return list;
    });

    const hasExec = computed(() => result.value?.summary?.some(r => "exec_pct" in r));
    const hasUnpaid = computed(() => result.value?.summary?.some(r => "unpaid_bo" in r));
    const hasUncontracted = computed(() => result.value?.summary?.some(r => "uncontracted" in r));
    const hasRisks = computed(() => result.value?.summary?.some(r => r.risk_level));
    const analytics = computed(() => result.value?.analytics || []);
    const currentTourStep = computed(() => TOUR_STEPS[tourIndex.value] || TOUR_STEPS[0]);
    const appShellClasses = computed(() => ({
      "sidebar-right": ui.sidebar === "right",
    }));

    const stepSummary1 = computed(() => {
      const parts = [];
      if (form.section) {
        const s = sections.value.find(x => x.id === form.section);
        if (s) parts.push(shortSectionTitle(s.title));
      } else {
        parts.push("Все");
      }
      if (form.types.length) parts.push(form.types.length + " " + plural(form.types.length, "тип", "типа", "типов"));
      return parts.join(" · ");
    });

    const periodSummary = computed(() => {
      const p = form.period;
      if (p.type === "as_of") return p.date ? `на ${p.date}` : "на дату";
      if (p.type === "range") return p.date_from && p.date_to ? `${p.date_from} – ${p.date_to}` : "период";
      if (p.type === "compare") return p.date_a && p.date_b ? `${p.date_a} ↔ ${p.date_b}` : "сравнение";
      return "без ограничения";
    });

    const selectedObjectsResolved = computed(() => {
      return form.objects.map(id => {
        const cached = objectsCache.value[id];
        if (cached) return cached;
        const parts = String(id).split("|");
        return { id, name: parts[3] || id, type: parts[0] || "", kcsr: parts[1] || "", dopkr: parts[2] || "" };
      });
    });

    const snapshotsAvailable = computed(() => {
      return form.period.type === "compare" && !!result.value;
    });

    const snapshotA = computed(() => buildSnapshot(form.period.date_a));
    const snapshotB = computed(() => buildSnapshot(form.period.date_b));

    function buildSnapshot(dateStr) {
      const out = {};
      if (!result.value || !dateStr) return out;
      const dyn = result.value.dynamic || [];
      // ищем запись с таким же месяцем (YYYY-MM)
      const month = dateStr.slice(0, 7);
      const match = dyn.find(d => (d.month || "").startsWith(month));
      if (match) {
        for (const m of result.value.metric_meta || []) out[m.code] = match[m.code] || 0;
      } else if (dyn.length) {
        // фолбэк: суммируем все точки до этой даты включительно
        for (const m of result.value.metric_meta || []) out[m.code] = 0;
        for (const d of dyn) {
          if ((d.month || "") <= month) {
            for (const m of result.value.metric_meta || []) out[m.code] += (d[m.code] || 0);
          }
        }
      }
      return out;
    }

    function snapDelta(code) {
      const a = snapshotA.value[code] || 0;
      const b = snapshotB.value[code] || 0;
      if (!a && !b) return { visible: false };
      if (!a) return { visible: true, up: b > 0, text: "новое" };
      const diff = ((b - a) / Math.abs(a)) * 100;
      if (!isFinite(diff)) return { visible: false };
      const sign = diff >= 0 ? "+" : "−";
      return { visible: true, up: diff >= 0, text: `${sign}${Math.abs(diff).toFixed(1)}%` };
    }

    const availableTabs = computed(() => {
      if (!result.value) return [];
      const r = result.value;
      const out = [
        { id: "summary", title: "Сводная", count: (r.summary || []).length },
        { id: "chart",   title: "Сравнение", count: (r.summary || []).length },
        { id: "dynamic", title: "Динамика", count: (r.dynamic || []).length },
      ];
      if (form.period.type === "compare") {
        out.push({ id: "snap", title: "Снимки A↔B", count: 2 });
      }
      out.push({ id: "details", title: "Детализация", count: (r.details || []).length });
      return out;
    });

    const resultSubtitle = computed(() => {
      const r = result.value;
      if (!r) return "";
      const parts = [];
      if (form.section) {
        const s = sections.value.find(x => x.id === form.section);
        if (s) parts.push(shortSectionTitle(s.title));
      }
      parts.push(periodSummary.value);
      const totalDetails = (r.details || []).length;
      if (totalDetails) parts.push(`${totalDetails} ${plural(totalDetails, "факт","факта","фактов")} в детализации`);
      return parts.join(" · ");
    });

    const healthSourcesShort = computed(() => {
      if (!health.value || !health.value.sources) return {};
      const map = { planning: "РЧБ", agreements: "Согл.", procurement: "ГЗ", buau: "БУ/АУ" };
      const out = {};
      for (const [k, v] of Object.entries(health.value.sources)) {
        out[map[k] || k] = v;
      }
      return out;
    });

    /* ─── Watchers ──────────────────────────── */
    watch(tab, async () => { await nextTick(); renderCharts(); });
    watch(theme, () => { nextTick(renderCharts); });

    onMounted(loadInitial);

    return {
      // state
      health, healthSourcesShort, objectTypes, sections, metrics, presets, groupedMetrics,
      objects, loadingObjects, loadingResult, reloading, result,
      tab, form, theme, ui, settingsOpen, savedPresets, toasts,
      smartQuery, smartResults, smartLoading, voiceActive, quickQuestions,
      expandedObjects, expandedSummary, tourOpen, tourIndex, chatOpen,
      chartCanvas, barCanvas,
      // computed
      kpis, hasExec, hasUnpaid, hasUncontracted, hasRisks, analytics, appShellClasses, currentTourStep,
      stepSummary1, periodSummary, selectedObjectsResolved,
      snapshotsAvailable, snapshotA, snapshotB, snapDelta,
      availableTabs, resultSubtitle,
      // methods
      onSmartInput, runSmartSearch, submitSmartSearch, clearSmartSearch, selectSmartResult,
      useQuickQuestion, startVoiceInput, buildQuickReport, setUi, applyUiSettings,
      onSearchInput, clearQuery, reloadObjects, toggleType, toggleMetric, removeObject,
      applyPreset, isPresetActive, resetForm, buildSelection, exportExcel, reload,
      toggleTheme, saveCurrentAsPreset, loadSavedPreset, deleteSavedPreset,
      dismissToast, riskClass, riskTitle, toggleObjectText, toggleSummaryText, startTour, nextTourStep, closeTour,
      // formatters
      formatMoney, formatMoneyShort, formatKpi, formatPct, formatDelta, formatCount, plural,
      shortSectionTitle, sourceShort, pctColor, smartTitle, smartContext, smartTags,
    };
  },
}).mount("#app");
