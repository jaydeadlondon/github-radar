/* GitHub Radar dashboard — ECharts helpers (v0.6). */
/* Global state shared with app.js (defined in app.js). */
/* eslint-disable no-undef */
const chart = echarts.init(document.getElementById("chart"));
const AXIS_TEXT_COLOR = getComputedStyle(document.body)
  .getPropertyValue("--text-muted")
  .trim();
const CHART_COLORS = {
  line: getComputedStyle(document.body).getPropertyValue("--accent").trim(),
  accentStrong: getComputedStyle(document.body)
    .getPropertyValue("--accent-strong")
    .trim(),
  average: getComputedStyle(document.body).getPropertyValue("--yellow").trim(),
  split: getComputedStyle(document.body).getPropertyValue("--border").trim(),
  text: AXIS_TEXT_COLOR,
};
function baseGrid(withZoom = false) {
  return { left: 48, right: 16, top: 16, bottom: withZoom ? 62 : 36 };
}
/** Wheel zoom on the plot plus a draggable range slider underneath. */
function baseDataZoom() {
  return [
    {
      type: "inside",
      throttle: 50,
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
    },
    {
      type: "slider",
      height: 18,
      bottom: 12,
      borderColor: CHART_COLORS.split,
      fillerColor: "rgba(88,166,255,0.15)",
      handleStyle: { color: CHART_COLORS.line },
      textStyle: { color: CHART_COLORS.text, fontSize: 10 },
    },
  ];
}
function resetZoom() {
  chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
}
function refreshChartColors() {
  CHART_COLORS.line = getComputedStyle(document.body)
    .getPropertyValue("--accent")
    .trim();
  CHART_COLORS.accentStrong = getComputedStyle(document.body)
    .getPropertyValue("--accent-strong")
    .trim();
  CHART_COLORS.average = getComputedStyle(document.body)
    .getPropertyValue("--yellow")
    .trim();
  CHART_COLORS.split = getComputedStyle(document.body)
    .getPropertyValue("--border")
    .trim();
  CHART_COLORS.text = getComputedStyle(document.body)
    .getPropertyValue("--text-muted")
    .trim();
  chart.setOption({
    xAxis: [
      {
        axisLine: { lineStyle: { color: CHART_COLORS.split } },
        axisLabel: { color: CHART_COLORS.text },
      },
    ],
    yAxis: [
      {
        axisLine: { lineStyle: { color: CHART_COLORS.split } },
        axisLabel: { color: CHART_COLORS.text },
      },
    ],
  });
}
function baseTooltip() {
  return {
    trigger: "axis",
    backgroundColor: "rgba(22,27,34,0.92)",
    borderColor: CHART_COLORS.split,
    textStyle: { color: "#e6edf3", fontSize: 12 },
    valueFormatter: (value) => new Intl.NumberFormat("en-US").format(value),
  };
}
function emptyChart(message) {
  chart.clear();
  chart.setOption({
    title: {
      text: message,
      left: "center",
      top: "middle",
      textStyle: {
        color: CHART_COLORS.text,
        fontSize: 13,
        fontWeight: "normal",
      },
    },
  });
}
/**
 * Render the daily star series produced by /api/v1/analytics/series.
 * @param {string} repoName - repository full name (for the tooltip)
 * @param {Array<{day: string, stars: number, delta: number}>} points
 * @param {{mode?: string}} options
 */
function renderSeriesChart(repoName, points, options = {}) {
  if (!points.length) {
    emptyChart("No snapshots yet for this repository");
    return;
  }
  const mode = options.mode || "stars";
  const days = points.map((point) => point.day);
  const isDelta = mode === "delta";
  const isGrowth = mode === "growth";
  chart.clear();
  chart.setOption({
    tooltip: isGrowth ? percentTooltip() : baseTooltip(),
    grid: baseGrid(true),
    dataZoom: baseDataZoom(),
    xAxis: {
      type: "category",
      data: days,
      boundaryGap: isDelta,
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text },
    },
    yAxis: {
      type: options.logScale && mode === "stars" ? "log" : "value",
      logBase: 10,
      min:
        options.logScale && mode === "stars"
          ? null
          : isDelta
            ? 0
            : isGrowth
              ? (value) => Math.floor(Math.min(0, value.min))
              : (value) => Math.max(0, Math.floor(value.min * 0.95)),
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: {
        color: CHART_COLORS.text,
        formatter: isGrowth ? "{value}%" : undefined,
      },
      splitLine: { lineStyle: { color: CHART_COLORS.split, opacity: 0.5 } },
    },
    series: [
      {
        ...modeSeries(repoName, points, mode),
        markArea: burstMarkArea(options.bursts, mode),
      },
      ...(options.smooth ? averageSeries(points, mode) : []),
    ],
  });
}
/** Shade the days that the burst detector flagged. */
function burstMarkArea(bursts, mode) {
  if (!bursts || !bursts.length) return undefined;
  const color =
    mode === "delta" ? "rgba(248,81,73,0.18)" : "rgba(210,153,34,0.16)";
  return {
    silent: true,
    itemStyle: { color },
    label: { show: false },
    data: bursts.map((event) => [
      { xAxis: event.start_day, name: "burst" },
      { xAxis: event.end_day },
    ]),
  };
}
function modeSeries(repoName, points, mode) {
  if (mode === "delta") {
    return deltaBarSeries(
      `${repoName} — daily change`,
      points.map((point) => point.delta),
    );
  }
  if (mode === "growth") {
    return starLineSeries(`${repoName} — growth`, growthValues(points));
  }
  return starLineSeries(
    repoName,
    points.map((point) => point.stars),
  );
}
/** Percent growth of every point relative to the first day of the window. */
function growthValues(points) {
  const base = Math.max(points[0].stars, 1);
  return points.map(
    (point) => Math.round((point.stars / base - 1) * 10000) / 100,
  );
}
/** Moving-average overlay; the API fills stars_avg / delta_avg. */
function averageSeries(points, mode) {
  if (mode === "growth") return [];
  const key = mode === "delta" ? "delta_avg" : "stars_avg";
  const values = points.map((point) => point[key]);
  if (values.every((value) => value === null || value === undefined)) return [];
  return [
    {
      name: "Moving average",
      type: "line",
      data: values,
      smooth: true,
      symbol: "none",
      connectNulls: false,
      z: 3,
      lineStyle: { color: CHART_COLORS.average, width: 2, type: "dashed" },
      itemStyle: { color: CHART_COLORS.average },
    },
  ];
}
function percentTooltip() {
  return {
    ...baseTooltip(),
    valueFormatter: (value) =>
      `${new Intl.NumberFormat("en-US").format(value)}%`,
  };
}
function deltaBarSeries(name, values) {
  return {
    name,
    type: "bar",
    data: values,
    barMaxWidth: 18,
    itemStyle: { color: CHART_COLORS.line, borderRadius: [2, 2, 0, 0] },
    emphasis: { itemStyle: { color: CHART_COLORS.accentStrong } },
  };
}
function starLineSeries(name, values) {
  return {
    name,
    type: "line",
    data: values,
    smooth: true,
    symbol: "circle",
    symbolSize: 5,
    lineStyle: { color: CHART_COLORS.line, width: 2 },
    itemStyle: { color: CHART_COLORS.line },
    areaStyle: {
      color: {
        type: "linear",
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: "rgba(88,166,255,0.25)" },
          { offset: 1, color: "rgba(88,166,255,0.02)" },
        ],
      },
    },
  };
}
function resizeChart() {
  chart.resize();
}
window.addEventListener("resize", resizeChart);
