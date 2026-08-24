/* GitHub Radar dashboard — ECharts helpers (v0.4). */

/* Global state shared with app.js (defined in app.js). */
/* eslint-disable no-undef */

const chart = echarts.init(document.getElementById("chart"));

const AXIS_TEXT_COLOR = getComputedStyle(document.body)
  .getPropertyValue("--text-muted")
  .trim();

const CHART_COLORS = {
  line: getComputedStyle(document.body).getPropertyValue("--accent").trim(),
  split: getComputedStyle(document.body).getPropertyValue("--border").trim(),
  text: AXIS_TEXT_COLOR,
};

function baseGrid() {
  return { left: 48, right: 16, top: 16, bottom: 36 };
}

function refreshChartColors() {
  CHART_COLORS.line = getComputedStyle(document.body)
    .getPropertyValue("--accent")
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
 * Render a line chart of star counts over time.
 * @param {string} repoName - repository full name (for the title)
 * @param {Array<{observed_at: string, stargazers_count: number}>} snapshots
 */
function renderStarChart(repoName, snapshots) {
  if (!snapshots.length) {
    emptyChart("No snapshots yet for this repository");
    return;
  }
  const dates = snapshots.map((s) => s.observed_at.slice(0, 10));
  const stars = snapshots.map((s) => s.stargazers_count);

  chart.setOption({
    tooltip: baseTooltip(),
    grid: baseGrid(),
    xAxis: {
      type: "category",
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text },
    },
    yAxis: {
      type: "value",
      min: (value) => Math.max(0, Math.floor(value.min * 0.95)),
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text },
      splitLine: { lineStyle: { color: CHART_COLORS.split, opacity: 0.5 } },
    },
    series: [
      {
        name: repoName,
        type: "line",
        data: stars,
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
      },
    ],
  });
}

function resizeChart() {
  chart.resize();
}

window.addEventListener("resize", resizeChart);
