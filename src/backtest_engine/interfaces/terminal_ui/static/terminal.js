const SVG_NS = "http://www.w3.org/2000/svg";

function readDashboardPayload() {
    const source = document.getElementById("dashboard-data");
    if (!source) {
        return null;
    }
    try {
        return JSON.parse(source.textContent || "null");
    } catch {
        return null;
    }
}

function createSvgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => {
        element.setAttribute(key, String(value));
    });
    return element;
}

function setAttributes(element, attributes = {}) {
    Object.entries(attributes).forEach(([key, value]) => {
        element.setAttribute(key, String(value));
    });
}

function clearSvg(svg) {
    while (svg.firstChild) {
        svg.removeChild(svg.firstChild);
    }
}

function chartSize(svg) {
    const width = Math.max(0, Math.floor(svg.clientWidth));
    const height = Math.max(0, Math.floor(svg.clientHeight));
    return { width, height };
}

function finitePoints(points) {
    if (!Array.isArray(points)) {
        return [];
    }
    return points
        .map((point, index) => ({
            index,
            timestamp: Date.parse(point.timestamp_utc),
            value: Number(point.value),
        }))
        .filter((point) => Number.isFinite(point.value));
}

function domain(values, fallbackPadding = 1) {
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
        min = -fallbackPadding;
        max = fallbackPadding;
    }
    if (min === max) {
        min -= fallbackPadding;
        max += fallbackPadding;
    }
    const padding = (max - min) * 0.06;
    return [min - padding, max + padding];
}

function linePath(points, xScale, yScale) {
    return points
        .map((point, index) => `${index === 0 ? "M" : "L"}${xScale(point)},${yScale(point.value)}`)
        .join(" ");
}

function panelSeries(panel, fallbackKey) {
    if (panel && Array.isArray(panel.series) && panel.series.length > 0) {
        return panel.series;
    }
    return [{ key: fallbackKey, label: "", points: panel ? panel.points : [] }];
}

function formatDate(timestamp) {
    if (!Number.isFinite(timestamp)) {
        return "";
    }
    return new Date(timestamp).toISOString().slice(0, 10);
}

function formatCompact(value) {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}m`;
    }
    if (abs >= 1_000) {
        return `${(value / 1_000).toFixed(1)}k`;
    }
    if (abs < 1 && abs > 0) {
        return value.toFixed(4);
    }
    return value.toFixed(2);
}

function formatPercent(value) {
    return `${(value * 100).toFixed(1)}%`;
}

function formatterForKind(kind) {
    return kind === "drawdown" ? formatPercent : formatCompact;
}

function estimateLegendWidth(label) {
    return Math.max(52, label.length * 6.4 + 24);
}

function renderSeries(svg, panel, options) {
    clearSvg(svg);
    if (!panel || panel.status !== "available") {
        return;
    }
    const seriesList = panelSeries(panel, options.kind)
        .map((series) => ({
            key: String(series.key || options.kind).toLowerCase().replace(/[^a-z0-9_-]/g, ""),
            label: String(series.label || ""),
            points: finitePoints(series.points),
        }))
        .filter((series) => series.points.length > 0);
    if (seriesList.length < 1) {
        return;
    }
    const allPoints = seriesList.flatMap((series) => series.points);

    const { width, height } = chartSize(svg);
    if (width < 80 || height < 60) {
        return;
    }
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const valueFormatter = formatterForKind(options.kind);
    const markerTexts = seriesList.map((series) => {
        const last = series.points[series.points.length - 1];
        const valueText = valueFormatter(last.value);
        return seriesList.length > 1 ? `${series.label || series.key} ${valueText}` : valueText;
    });
    const maxMarkerWidth = markerTexts.reduce(
        (maxWidth, text) => Math.max(maxWidth, Math.max(34, text.length * 5.9 + 8)),
        0,
    );
    const pad = {
        top: options.kind === "equity" ? 28 : 14,
        right: Math.max(78, Math.ceil(maxMarkerWidth + 14)),
        bottom: 30,
        left: 10,
    };
    const plotWidth = Math.max(1, width - pad.left - pad.right);
    const plotHeight = Math.max(1, height - pad.top - pad.bottom);
    const finiteTimes = allPoints.map((point) => point.timestamp).filter(Number.isFinite);
    const useTime = finiteTimes.length === allPoints.length && Math.min(...finiteTimes) !== Math.max(...finiteTimes);
    const xMin = useTime ? Math.min(...finiteTimes) : 0;
    const maxIndex = Math.max(...seriesList.map((series) => series.points.length - 1), 1);
    const xMax = useTime ? Math.max(...finiteTimes) : maxIndex;
    const values = allPoints.map((point) => point.value);
    if (options.includeZero) {
        values.push(0);
    }
    let [yMin, yMax] = domain(values);
    if (options.kind === "drawdown") {
        yMax = 0;
        if (yMin >= 0) {
            yMin = -0.01;
        }
    }
    const xScale = (point) => {
        const xValue = useTime ? point.timestamp : point.index;
        return pad.left + ((xValue - xMin) / (xMax - xMin || 1)) * plotWidth;
    };
    const yScale = (value) => pad.top + ((yMax - value) / (yMax - yMin || 1)) * plotHeight;

    [0, 0.5, 1].forEach((fraction) => {
        const y = pad.top + fraction * plotHeight;
        const tickValue = yMax - fraction * (yMax - yMin);
        svg.appendChild(createSvgElement("line", {
            class: "chart-grid-line",
            x1: pad.left,
            x2: width - pad.right,
            y1: y,
            y2: y,
        }));
        const tick = createSvgElement("text", {
            class: "chart-tick chart-tick--y",
            x: width - pad.right + 8,
            y,
            "text-anchor": "start",
            "dominant-baseline": "middle",
        });
        tick.textContent = valueFormatter(tickValue);
        svg.appendChild(tick);
    });

    svg.appendChild(createSvgElement("line", {
        class: "chart-axis",
        x1: width - pad.right,
        x2: width - pad.right,
        y1: pad.top,
        y2: height - pad.bottom,
    }));

    svg.appendChild(createSvgElement("line", {
        class: "chart-axis",
        x1: pad.left,
        x2: width - pad.right,
        y1: height - pad.bottom,
        y2: height - pad.bottom,
    }));

    if (options.includeZero && yMin < 0 && yMax > 0) {
        const zeroY = yScale(0);
        svg.appendChild(createSvgElement("line", {
            class: "chart-zero-line",
            x1: pad.left,
            x2: width - pad.right,
            y1: zeroY,
            y2: zeroY,
        }));
    }

    const xTickFractions = width >= 560 ? [0, 0.25, 0.5, 0.75, 1] : [0, 0.5, 1];
    xTickFractions.forEach((fraction) => {
        const x = pad.left + fraction * plotWidth;
        const value = xMin + fraction * (xMax - xMin);
        svg.appendChild(createSvgElement("line", {
            class: "chart-grid-line chart-grid-line--vertical",
            x1: x,
            x2: x,
            y1: pad.top,
            y2: height - pad.bottom,
        }));
        const label = createSvgElement("text", {
            class: "chart-tick chart-tick--x",
            x,
            y: height - 8,
            "text-anchor": fraction === 0 ? "start" : fraction === 1 ? "end" : "middle",
        });
        label.textContent = useTime ? formatDate(value) : String(Math.round(value));
        svg.appendChild(label);
    });

    if (options.kind === "equity" && seriesList.length > 1) {
        let legendX = pad.left;
        seriesList.forEach((series) => {
            const legendLabel = series.label || series.key;
            const swatch = createSvgElement("line", {
                class: `chart-legend-swatch chart-line--${series.key}`,
                x1: legendX,
                x2: legendX + 14,
                y1: 11,
                y2: 11,
            });
            svg.appendChild(swatch);
            const legend = createSvgElement("text", {
                class: "chart-legend",
                x: legendX + 18,
                y: 14,
            });
            legend.textContent = legendLabel;
            svg.appendChild(legend);
            legendX += estimateLegendWidth(legendLabel);
        });
    }

    seriesList.forEach((series, seriesIndex) => {
        svg.appendChild(createSvgElement("path", {
            class: `chart-line chart-line--${options.kind} chart-line--${series.key}`,
            d: linePath(series.points, xScale, yScale),
        }));

        const last = series.points[series.points.length - 1];
        const markerY = Math.max(pad.top + 7, Math.min(height - pad.bottom - 7, yScale(last.value)));
        const markerText = seriesList.length > 1
            ? `${series.label || series.key} ${valueFormatter(last.value)}`
            : valueFormatter(last.value);
        const textWidth = Math.max(34, markerText.length * 5.9 + 8);
        const axisX = width - pad.right;
        const markerX = axisX + 4;
        svg.appendChild(createSvgElement("rect", {
            class: `chart-axis-marker chart-axis-marker--${series.key}`,
            x: markerX,
            y: markerY - 8,
            width: textWidth,
            height: 16,
            rx: 2,
        }));
        const marker = createSvgElement("text", {
            class: "chart-axis-marker-text",
            x: markerX + textWidth / 2,
            y: markerY,
            "text-anchor": "middle",
            "dominant-baseline": "middle",
        });
        marker.textContent = markerText;
        svg.appendChild(marker);
    });

    const hoverGroup = createSvgElement("g", {
        class: "chart-hover",
        visibility: "hidden",
    });
    const hoverLine = createSvgElement("line", {
        class: "chart-hover-line",
        y1: pad.top,
        y2: height - pad.bottom,
    });
    const tooltipBox = createSvgElement("rect", {
        class: "chart-tooltip-bg",
        rx: 3,
    });
    const tooltipText = createSvgElement("text", {
        class: "chart-tooltip-text",
    });
    hoverGroup.appendChild(hoverLine);
    hoverGroup.appendChild(tooltipBox);
    hoverGroup.appendChild(tooltipText);
    svg.appendChild(hoverGroup);

    const hitArea = createSvgElement("rect", {
        class: "chart-hit-area",
        x: pad.left,
        y: pad.top,
        width: plotWidth,
        height: plotHeight,
    });
    svg.appendChild(hitArea);

    const nearestPoint = (points, target) => points.reduce((nearest, point) => {
        const pointValue = useTime ? point.timestamp : point.index;
        const nearestValue = useTime ? nearest.timestamp : nearest.index;
        return Math.abs(pointValue - target) < Math.abs(nearestValue - target) ? point : nearest;
    }, points[0]);

    const updateHover = (event) => {
        const box = svg.getBoundingClientRect();
        if (box.width <= 0 || box.height <= 0) {
            return;
        }
        const localX = ((event.clientX - box.left) / box.width) * width;
        const clampedX = Math.max(pad.left, Math.min(width - pad.right, localX));
        const target = useTime
            ? xMin + ((clampedX - pad.left) / plotWidth) * (xMax - xMin)
            : ((clampedX - pad.left) / plotWidth) * maxIndex;
        const nearestRows = seriesList.map((series) => ({
            series,
            point: nearestPoint(series.points, target),
        }));
        const anchorPoint = nearestRows[0].point;
        const hoverX = xScale(anchorPoint);
        setAttributes(hoverLine, { x1: hoverX, x2: hoverX });
        while (tooltipText.firstChild) {
            tooltipText.removeChild(tooltipText.firstChild);
        }
        const lines = [
            formatDate(anchorPoint.timestamp),
            ...nearestRows.map((row) => {
                const label = row.series.label || row.series.key;
                return `${label}: ${valueFormatter(row.point.value)}`;
            }),
        ];
        const tooltipWidth = Math.max(...lines.map((line) => line.length)) * 6.4 + 14;
        const tooltipHeight = lines.length * 14 + 10;
        const tooltipX = Math.min(width - pad.right - tooltipWidth - 4, Math.max(pad.left + 4, hoverX + 10));
        const tooltipY = pad.top + 8;
        setAttributes(tooltipBox, {
            x: tooltipX,
            y: tooltipY,
            width: tooltipWidth,
            height: tooltipHeight,
        });
        lines.forEach((line, index) => {
            const tspan = createSvgElement("tspan", {
                x: tooltipX + 7,
                y: index === 0 ? tooltipY + 15 : tooltipY + 15 + index * 14,
            });
            tspan.textContent = line;
            tooltipText.appendChild(tspan);
        });
        hoverGroup.setAttribute("visibility", "visible");
    };

    hitArea.addEventListener("pointermove", updateHover);
    hitArea.addEventListener("pointerleave", () => {
        hoverGroup.setAttribute("visibility", "hidden");
    });
}

function correlationColor(value) {
    const bounded = Math.max(-1, Math.min(1, value));
    if (bounded >= 0) {
        const intensity = Math.round(245 - bounded * 95);
        return `rgb(${intensity}, ${Math.round(248 - bounded * 50)}, ${Math.round(246 - bounded * 35)})`;
    }
    const magnitude = Math.abs(bounded);
    return `rgb(${Math.round(250 - magnitude * 50)}, ${Math.round(244 - magnitude * 105)}, ${Math.round(238 - magnitude * 128)})`;
}

function renderHeatmap(svg, panel) {
    clearSvg(svg);
    if (!panel || panel.status !== "available") {
        return;
    }
    const strategies = Array.isArray(panel.strategy_ids) ? panel.strategy_ids : [];
    const cells = Array.isArray(panel.cells) ? panel.cells : [];
    if (strategies.length < 2 || cells.length === 0) {
        return;
    }

    const { width, height } = chartSize(svg);
    if (width < 120 || height < 100) {
        return;
    }
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const labelWidth = Math.min(126, Math.max(58, width * 0.22));
    const topPad = 20;
    const rightPad = 8;
    const bottomPad = 8;
    const matrixSize = Math.max(
        1,
        Math.min(width - labelWidth - rightPad, height - topPad - bottomPad),
    );
    const cellSize = matrixSize / strategies.length;
    const cellByPair = new Map(
        cells.map((cell) => [`${cell.row_strategy_id}\u0000${cell.column_strategy_id}`, cell]),
    );

    strategies.forEach((strategyId, rowIndex) => {
        const y = topPad + rowIndex * cellSize + cellSize / 2;
        const label = createSvgElement("text", {
            class: "heatmap-label",
            x: labelWidth - 8,
            y,
            "text-anchor": "end",
            "dominant-baseline": "middle",
        });
        label.textContent = String(strategyId);
        svg.appendChild(label);
    });

    strategies.forEach((strategyId, columnIndex) => {
        const x = labelWidth + columnIndex * cellSize + cellSize / 2;
        const label = createSvgElement("text", {
            class: "heatmap-label",
            x,
            y: 12,
            "text-anchor": "middle",
        });
        label.textContent = String(strategyId).slice(0, Math.max(3, Math.floor(cellSize / 7)));
        svg.appendChild(label);
    });

    strategies.forEach((rowStrategyId, rowIndex) => {
        strategies.forEach((columnStrategyId, columnIndex) => {
            const cell = cellByPair.get(`${rowStrategyId}\u0000${columnStrategyId}`);
            const value = cell ? Number(cell.value) : null;
            const x = labelWidth + columnIndex * cellSize;
            const y = topPad + rowIndex * cellSize;
            svg.appendChild(createSvgElement("rect", {
                class: "heatmap-cell",
                x,
                y,
                width: Math.max(0, cellSize),
                height: Math.max(0, cellSize),
                fill: Number.isFinite(value) ? correlationColor(value) : "#f2efe9",
            }));
            if (Number.isFinite(value) && cellSize >= 34) {
                const text = createSvgElement("text", {
                    class: "heatmap-value",
                    x: x + cellSize / 2,
                    y: y + cellSize / 2,
                });
                text.textContent = value.toFixed(2);
                svg.appendChild(text);
            }
        });
    });
}

function renderDashboard(payload) {
    document.querySelectorAll("[data-chart='equity']").forEach((svg) => {
        renderSeries(svg, payload && payload.equity, { kind: "equity", includeZero: false });
    });
    document.querySelectorAll("[data-chart='drawdown']").forEach((svg) => {
        renderSeries(svg, payload && payload.drawdown, { kind: "drawdown", includeZero: true });
    });
    document.querySelectorAll("[data-chart='heatmap']").forEach((svg) => {
        renderHeatmap(svg, payload && payload.heatmap);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const payload = readDashboardPayload();
    let frame = 0;
    const scheduleRender = () => {
        if (frame) {
            window.cancelAnimationFrame(frame);
        }
        frame = window.requestAnimationFrame(() => {
            frame = 0;
            renderDashboard(payload);
        });
    };

    const observer = new ResizeObserver(scheduleRender);
    document.querySelectorAll(".viz-panel").forEach((panel) => {
        observer.observe(panel);
    });
    scheduleRender();
});
