const $ = (id) => document.getElementById(id);

const state = {
  rangeSeconds: 3600,
  samples: [],
  lastOkAt: 0,
  lastHistoryReloadAt: 0,
  historyMode: "raw",
  bucketSeconds: 1,
  maxPoints: 2000,
  samplingIntervalSeconds: 2,
  latestSample: null,
};

function fmtBytes(bytes) {
  if (bytes == null) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = Number(bytes);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return "--%";
  return `${Number(v).toFixed(1)}%`;
}

function fmtTemp(v) {
  if (v == null || Number.isNaN(v)) return "--°C";
  return `${Number(v).toFixed(1)}°C`;
}

function setConn(ok) {
  const pill = $("conn-pill");
  if (!pill) return;
  pill.textContent = ok ? "LIVE" : "OFFLINE";
  pill.style.borderColor = ok ? "rgba(87,255,154,0.62)" : "rgba(255,93,108,0.62)";
  pill.style.color = ok ? "#57ff9a" : "#ff5d6c";
}

function tickClock() {
  const el = $("clock");
  if (!el) return;
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  el.textContent = `${hh}:${mm}:${ss}`;
}

function renderStats(sample) {
  if (!sample) return;
  $("cpu-usage").textContent = fmtPct(sample.cpu.usage);
  $("cpu-temp").textContent = fmtTemp(sample.cpu.temp_c);

  $("mem-usage").textContent = fmtPct(sample.memory.percent);
  $("mem-used").textContent = `${fmtBytes(sample.memory.used_bytes)} / ${fmtBytes(sample.memory.total_bytes)}`;

  $("gpu-usage").textContent = fmtPct(sample.gpu.usage);
  $("gpu-temp").textContent = fmtTemp(sample.gpu.temp_c);
}

function normalize(values, minV, maxV) {
  const out = [];
  for (const v of values) {
    if (v == null || Number.isNaN(v)) out.push(null);
    else out.push(Math.max(minV, Math.min(maxV, Number(v))));
  }
  return out;
}

function polylinePoints(values, width, height, minV, maxV) {
  const pts = [];
  const n = values.length;
  if (n === 0) return "";
  const dx = width / Math.max(1, n - 1);
  for (let i = 0; i < n; i += 1) {
    const v = values[i];
    if (v == null) continue;
    const x = i * dx;
    const y = height - ((v - minV) / (maxV - minV)) * height;
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return pts.join(" ");
}

function polylinePointsInRect(values, x0, y0, w, h, minV, maxV) {
  const pts = [];
  const n = values.length;
  if (n === 0) return "";
  const dx = w / Math.max(1, n - 1);
  for (let i = 0; i < n; i += 1) {
    const v = values[i];
    if (v == null) continue;
    const x = x0 + i * dx;
    const y = y0 + h - ((v - minV) / (maxV - minV)) * h;
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return pts.join(" ");
}

function drawGrid(svg, x0, y0, w, h, rows, cols) {
  const ns = "http://www.w3.org/2000/svg";
  for (let r = 1; r < rows; r += 1) {
    const y = y0 + (h * r) / rows;
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", String(x0));
    line.setAttribute("x2", String(x0 + w));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("stroke", "rgba(107,215,255,0.10)");
    line.setAttribute("stroke-dasharray", "4 6");
    svg.appendChild(line);
  }
  for (let c = 1; c < cols; c += 1) {
    const x = x0 + (w * c) / cols;
    const line = document.createElementNS(ns, "line");
    line.setAttribute("y1", String(y0));
    line.setAttribute("y2", String(y0 + h));
    line.setAttribute("x1", String(x));
    line.setAttribute("x2", String(x));
    line.setAttribute("stroke", "rgba(107,215,255,0.08)");
    line.setAttribute("stroke-dasharray", "4 6");
    svg.appendChild(line);
  }
}

function drawSeries(svg, values, minV, maxV, color, x0, y0, w, h) {
  const ns = "http://www.w3.org/2000/svg";
  const pts = polylinePointsInRect(values, x0, y0, w, h, minV, maxV);
  if (!pts) return;

  const glow = document.createElementNS(ns, "polyline");
  glow.setAttribute("points", pts);
  glow.setAttribute("fill", "none");
  glow.setAttribute("stroke", color);
  glow.setAttribute("stroke-width", "5");
  glow.setAttribute("opacity", "0.18");
  glow.setAttribute("stroke-linecap", "round");
  glow.setAttribute("stroke-linejoin", "round");
  svg.appendChild(glow);

  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("stroke-linejoin", "round");
  svg.appendChild(line);
}

function fmtTimeShort(ts, spanSeconds = 0) {
  if (!ts) return "--";
  const d = new Date(ts * 1000);
  if (Number(spanSeconds) >= 86400 * 2) {
    return d.toLocaleDateString([], { month: "2-digit", day: "2-digit" });
  }
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function drawAxes(svg, x0, y0, w, h, minV, maxV, yTicks, yFmt, xTicks, minorYTicks = []) {
  const ns = "http://www.w3.org/2000/svg";
  const axisColor = "rgba(107,215,255,0.22)";
  const textColor = "rgba(137,164,192,0.85)";
  const font = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

  const yAxis = document.createElementNS(ns, "line");
  yAxis.setAttribute("x1", String(x0));
  yAxis.setAttribute("x2", String(x0));
  yAxis.setAttribute("y1", String(y0));
  yAxis.setAttribute("y2", String(y0 + h));
  yAxis.setAttribute("stroke", axisColor);
  svg.appendChild(yAxis);

  const xAxis = document.createElementNS(ns, "line");
  xAxis.setAttribute("x1", String(x0));
  xAxis.setAttribute("x2", String(x0 + w));
  xAxis.setAttribute("y1", String(y0 + h));
  xAxis.setAttribute("y2", String(y0 + h));
  xAxis.setAttribute("stroke", axisColor);
  svg.appendChild(xAxis);

  for (const v of minorYTicks || []) {
    if (v === minV || v === maxV) continue;
    const y = y0 + h - ((v - minV) / (maxV - minV)) * h;
    const tick = document.createElementNS(ns, "line");
    tick.setAttribute("x1", String(x0 - 2));
    tick.setAttribute("x2", String(x0));
    tick.setAttribute("y1", String(y));
    tick.setAttribute("y2", String(y));
    tick.setAttribute("stroke", "rgba(107,215,255,0.12)");
    svg.appendChild(tick);
  }

  for (const v of yTicks) {
    const y = y0 + h - ((v - minV) / (maxV - minV)) * h;
    const tick = document.createElementNS(ns, "line");
    tick.setAttribute("x1", String(x0 - 4));
    tick.setAttribute("x2", String(x0));
    tick.setAttribute("y1", String(y));
    tick.setAttribute("y2", String(y));
    tick.setAttribute("stroke", axisColor);
    svg.appendChild(tick);

    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", String(x0 - 6));
    label.setAttribute("y", String(y));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("dominant-baseline", "middle");
    label.setAttribute("fill", textColor);
    label.setAttribute("font-size", "10");
    label.setAttribute("font-family", font);
    label.textContent = yFmt(v);
    svg.appendChild(label);
  }

  for (const t of xTicks) {
    const tick = document.createElementNS(ns, "line");
    tick.setAttribute("x1", String(t.x));
    tick.setAttribute("x2", String(t.x));
    tick.setAttribute("y1", String(y0 + h));
    tick.setAttribute("y2", String(y0 + h + 4));
    tick.setAttribute("stroke", axisColor);
    svg.appendChild(tick);

    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", String(t.x));
    label.setAttribute("y", String(y0 + h + 14));
    label.setAttribute("text-anchor", t.anchor);
    label.setAttribute("dominant-baseline", "middle");
    label.setAttribute("fill", textColor);
    label.setAttribute("font-size", "10");
    label.setAttribute("font-family", font);
    label.textContent = t.label;
    svg.appendChild(label);
  }
}

function renderSpark(svgId, values, color) {
  const svg = $(svgId);
  if (!svg) return;
  const w = 100;
  const h = 30;
  const inset = 0.6;
  svg.innerHTML = "";
  drawGrid(svg, inset, inset, w - inset * 2, h - inset * 2, 3, 6);
  drawAxes(svg, inset, inset, w - inset * 2, h - inset * 2, 0, 100, [], () => "", []);
  drawSeries(svg, values, 0, 100, color, inset, inset, w - inset * 2, h - inset * 2);
}

function renderCharts(samples) {
  const usageSvg = $("chart-usage");
  const tempSvg = $("chart-temp");
  if (!usageSvg || !tempSvg) return;

  const w = 600;
  const h = 200;

  usageSvg.innerHTML = "";
  tempSvg.innerHTML = "";
  const margin = { left: 44, right: 10, top: 10, bottom: 20 };
  const px = margin.left;
  const py = margin.top;
  const pw = w - margin.left - margin.right;
  const ph = h - margin.top - margin.bottom;

  drawGrid(usageSvg, px, py, pw, ph, 5, 4);
  drawGrid(tempSvg, px, py, pw, ph, 6, 4);

  const cpuU = normalize(samples.map((s) => s.cpu.usage), 0, 100);
  const memU = normalize(samples.map((s) => s.memory.percent), 0, 100);
  const gpuU = normalize(samples.map((s) => s.gpu.usage), 0, 100);

  const cpuT = normalize(samples.map((s) => s.cpu.temp_c), 0, 120);
  const gpuT = normalize(samples.map((s) => s.gpu.temp_c), 0, 120);

  const startTs = samples.length ? samples[0].ts : 0;
  const endTs = samples.length ? samples[samples.length - 1].ts : 0;
  const span = startTs && endTs ? Math.max(1, endTs - startTs) : 1;
  const fractions = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = fractions.map((f, idx) => {
    const ts = startTs && endTs ? Math.floor(startTs + span * f) : 0;
    const anchor = idx === 0 ? "start" : idx === fractions.length - 1 ? "end" : "middle";
    return { x: px + pw * f, label: fmtTimeShort(ts, span), anchor };
  });

  drawAxes(
    usageSvg,
    px,
    py,
    pw,
    ph,
    0,
    100,
    [0, 20, 40, 60, 80, 100],
    (v) => String(Math.round(v)),
    xTicks,
    [10, 30, 50, 70, 90],
  );

  drawAxes(
    tempSvg,
    px,
    py,
    pw,
    ph,
    0,
    120,
    [0, 20, 40, 60, 80, 100, 120],
    (v) => String(Math.round(v)),
    xTicks,
    [10, 30, 50, 70, 90, 110],
  );

  drawSeries(usageSvg, cpuU, 0, 100, "#57ff9a", px, py, pw, ph);
  drawSeries(usageSvg, memU, 0, 100, "#6bd7ff", px, py, pw, ph);
  drawSeries(usageSvg, gpuU, 0, 100, "#ffcc66", px, py, pw, ph);

  drawSeries(tempSvg, cpuT, 0, 120, "#57ff9a", px, py, pw, ph);
  drawSeries(tempSvg, gpuT, 0, 120, "#ffcc66", px, py, pw, ph);

  renderSpark("spark-cpu", cpuU.slice(-60), "#57ff9a");
  renderSpark("spark-mem", memU.slice(-60), "#6bd7ff");
  renderSpark("spark-gpu", gpuU.slice(-60), "#ffcc66");
}

async function fetchHistory(seconds) {
  const resp = await fetch(`api/v1/metrics/history?seconds=${encodeURIComponent(seconds)}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(`history http ${resp.status}`);
  return await resp.json();
}

async function fetchLatest() {
  const resp = await fetch("api/v1/metrics/latest", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(`latest http ${resp.status}`);
  return await resp.json();
}

async function fetchStatus() {
  const resp = await fetch("api/v1/metrics/status", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(`status http ${resp.status}`);
  return await resp.json();
}

function updateMeta(samples) {
  const el = $("sample-meta");
  if (!el) return;
  if (!samples.length) {
    el.textContent = "no samples";
    return;
  }
  const first = samples[0].ts;
  const last = samples[samples.length - 1].ts;
  const span = Math.max(1, last - first);
  const win =
    span >= 86400
      ? `${new Date(first * 1000).toLocaleString()} → ${new Date(last * 1000).toLocaleString()}`
      : `${new Date(first * 1000).toLocaleTimeString()} → ${new Date(last * 1000).toLocaleTimeString()}`;

  const ds =
    state.bucketSeconds && state.bucketSeconds > 1
      ? ` downsample=${state.bucketSeconds}s`
      : "";
  el.textContent = `samples=${samples.length} window=[${win}]${ds}`;
}

function updateSourceMeta(status) {
  const el = $("source-meta");
  if (!el) return;

  if (!status) {
    el.textContent = "";
    return;
  }

  const cpu = status.cpu_temp || {};
  let cpuPart = "cpuTemp: n/a";
  if (cpu.method === "hwmon" && cpu.source) {
    const chip = cpu.source.chip || "hwmon";
    const label = cpu.source.label || "";
    cpuPart = `cpuTemp: ${chip}${label ? "/" + label : ""}`;
  } else if (cpu.method === "sysfs") {
    cpuPart = "cpuTemp: sysfs";
  } else if (cpu.method === "psutil") {
    cpuPart = "cpuTemp: psutil";
  } else if (cpu.method === "thermal_zone") {
    cpuPart = "cpuTemp: thermal_zone";
  }

  const sampling = status.sampling || {};
  const gpu = (sampling.gpu || {});
  let gpuPart = "gpu: n/a";
  if (gpu.enabled === false) {
    gpuPart = "gpu: off";
  } else if (gpu.mode) {
    gpuPart = `gpu: ${gpu.mode}`;
  } else if (gpu.last_error) {
    gpuPart = "gpu: unavailable";
  } else if (gpu.enabled === true) {
    gpuPart = "gpu: idle";
  }

  el.textContent = `${cpuPart} · ${gpuPart}`;
}

async function reloadRange(seconds, options = { updateStatsFromHistory: true }) {
  const data = await fetchHistory(seconds);
  state.samples = (data.samples || []).map((x) => x);
  state.historyMode = data.mode || "raw";
  state.bucketSeconds = Number(data.bucket_seconds || 1);
  state.maxPoints = Number(data.max_points || 2000);
  state.lastHistoryReloadAt = Date.now();

  const latest = state.samples[state.samples.length - 1] || null;
  if (options.updateStatsFromHistory) {
    renderStats(latest);
    state.latestSample = latest;
  }
  renderCharts(state.samples);
  updateMeta(state.samples);
  state.lastOkAt = Date.now();
  setConn(true);
}

function shouldAppendLive() {
  const interval = Number(state.samplingIntervalSeconds || 2);
  const bucket = Number(state.bucketSeconds || 1);
  // 桶大小接近采样间隔时，允许直接追加最新点；否则用定期 reloadRange 刷新图表
  return bucket <= Math.max(2, Math.ceil(interval * 2));
}

async function maybeRefreshHistory() {
  const bucket = Number(state.bucketSeconds || 1);
  const refreshEverySec = Math.max(10, Math.min(300, bucket));
  if (Date.now() - state.lastHistoryReloadAt < refreshEverySec * 1000) return;
  try {
    await reloadRange(state.rangeSeconds, { updateStatsFromHistory: false });
    if (state.latestSample) renderStats(state.latestSample);
  } catch (e) {
    // ignore, keep last chart
  }
}

async function pollLatest() {
  try {
    const data = await fetchLatest();
    const sample = data.sample;
    if (sample) {
      state.latestSample = sample;
      renderStats(sample);
      if (shouldAppendLive()) {
        state.samples.push(sample);
        if (state.samples.length > 5000) state.samples = state.samples.slice(-5000);
        renderCharts(state.samples);
        updateMeta(state.samples);
      } else {
        await maybeRefreshHistory();
      }
      state.lastOkAt = Date.now();
      setConn(true);
    }
  } catch (e) {
    if (Date.now() - state.lastOkAt > 8000) setConn(false);
  }
}

function bindRangeButtons() {
  const buttons = document.querySelectorAll("button[data-range]");
  buttons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const seconds = Number(btn.getAttribute("data-range"));
      state.rangeSeconds = seconds;
      try {
        await reloadRange(seconds);
      } catch (e) {
        setConn(false);
      }
    });
  });
}

async function main() {
  tickClock();
  setInterval(tickClock, 1000);
  bindRangeButtons();

  try {
    const status = await fetchStatus();
    const sampling = status.sampling || {};
    if (sampling.sampling_interval_seconds != null) {
      state.samplingIntervalSeconds = Number(sampling.sampling_interval_seconds);
    }
    updateSourceMeta(status);
  } catch (e) {
    updateSourceMeta(null);
  }

  try {
    await reloadRange(state.rangeSeconds);
  } catch (e) {
    setConn(false);
  }
  setInterval(pollLatest, 2000);
}

window.addEventListener("DOMContentLoaded", main);
