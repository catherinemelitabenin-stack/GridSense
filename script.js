
"use strict";

let forecast = [];
let demandChart = null;
let refreshTimer = null;
let isUploading = false;
let usingUpload = false;

let batteryLevel = 78;
let batteryStatus = "Normal";

const CRITICAL_THRESHOLD = 200;
const REFRESH_INTERVAL = 5000;

// ==========================================
// LOAD FORECAST FROM FLASK
// ==========================================

async function loadForecast() {
    if (isUploading) return;

    const refreshButton = document.getElementById("refreshBtn");
    const refreshLabel = refreshButton?.querySelector(".refresh-label");
    const updatedLabel = document.getElementById("updatedLabel");

    if (refreshButton) refreshButton.disabled = true;
    if (refreshLabel) refreshLabel.textContent = "Loading forecast...";

    try {
        const response = await fetch("/api/forecast", {
            cache: "no-store"
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.error || "Forecast API returned an error."
            );
        }

        const data = Array.isArray(result)
            ? result
            : result.forecast;

        if (!Array.isArray(data) || data.length === 0) {
            throw new Error("No forecast data was returned.");
        }

        forecast = data;

        // Read battery information from Flask.
        batteryLevel = Number(
            result.battery_soc ?? data[0].battery_soc ?? 78
        );

        batteryStatus =
            result.battery_status ??
            data[0].battery_status ??
            "Normal";

        if (!Number.isFinite(batteryLevel)) {
            batteryLevel = 78;
        }

        batteryLevel = Math.max(0, Math.min(100, batteryLevel));

        updateSourceBadge(
            result.source || "SIMULATED DEMO",
            Boolean(result.is_live)
        );

        renderDashboard();

        if (updatedLabel) {
            updatedLabel.textContent = result.updated_at
                ? `Updated at ${result.updated_at}`
                : `Updated at ${new Date().toLocaleTimeString()}`;
        }

    } catch (error) {
        console.error("Could not load forecast:", error);

        const banner = document.getElementById("alertBanner");
        const heading = banner?.querySelector(".alert-copy strong");
        const message = document.getElementById("alertMessage");

        if (banner) banner.classList.remove("hidden");

        if (heading) {
            heading.textContent = "Unable to load forecast";
        }

        if (message) {
            message.textContent =
                error.message || "Check that app.py is running.";
        }

        if (updatedLabel) {
            updatedLabel.textContent = "Forecast unavailable";
        }

    } finally {
        if (refreshButton) refreshButton.disabled = false;

        if (refreshLabel) {
            refreshLabel.textContent = "Refresh forecast";
        }
    }
}

// ==========================================
// SOURCE BADGE
// ==========================================

function updateSourceBadge(source, isLive) {
    const badge = document.getElementById("sourceBadge");

    if (!badge) return;

    badge.textContent = `● ${source}`;

    badge.classList.toggle("live-source", isLive);
    badge.classList.toggle("demo-source", !isLive);
}

// ==========================================
// BATTERY DISPLAY
// ==========================================

function renderBattery() {
    const batteryCharge = document.getElementById("batteryCharge");
    const batteryFill = document.getElementById("batteryFill");
    const batteryTrack = document.querySelector(".battery-track");

    if (batteryCharge) {
        batteryCharge.innerHTML =
            `${batteryLevel.toFixed(1)}<small>%</small>`;

        batteryCharge.title = `Battery status: ${batteryStatus}`;
    }

    if (batteryFill) {
        batteryFill.style.width = `${batteryLevel}%`;

        if (batteryLevel <= 20) {
            batteryFill.style.backgroundColor = "#fb7185";
        } else if (batteryLevel <= 30) {
            batteryFill.style.backgroundColor = "#fbbf24";
        } else {
            batteryFill.style.backgroundColor = "#34d399";
        }
    }

    if (batteryTrack) {
        batteryTrack.setAttribute(
            "aria-valuenow",
            batteryLevel.toFixed(1)
        );

        batteryTrack.setAttribute(
            "aria-valuetext",
            `${batteryLevel.toFixed(1)}% — ${batteryStatus}`
        );
    }
}

// ==========================================
// RENDER DASHBOARD
// ==========================================

function renderDashboard() {
    if (!Array.isArray(forecast) || forecast.length === 0) {
        return;
    }

    const demands = forecast.map(item => Number(item.demand));

    if (demands.some(value => !Number.isFinite(value))) {
        console.error("Forecast contains invalid demand values.");
        return;
    }

    const peakDemand = Math.max(...demands);

    const alerts = forecast.filter(item =>
        Number(item.demand) >= CRITICAL_THRESHOLD
    );

    const firstMode = forecast[0].mode || "Not available";

    const peakDemandElement = document.getElementById("peakDemand");
    const currentModeElement = document.getElementById("currentMode");
    const alertCountElement = document.getElementById("alertCount");

    if (peakDemandElement) {
        peakDemandElement.innerHTML =
            `${peakDemand.toFixed(2)} <small>kW</small>`;
    }

    if (currentModeElement) {
        currentModeElement.textContent = firstMode;
    }

    if (alertCountElement) {
        alertCountElement.textContent = alerts.length;
    }

    // Update the battery using the values returned by Flask.
    renderBattery();

    // Overload alert banner.
    const banner = document.getElementById("alertBanner");
    const alertHeading = banner?.querySelector(".alert-copy strong");
    const alertMessage = document.getElementById("alertMessage");

    if (alerts.length > 0) {
        banner?.classList.remove("hidden");

        if (alertHeading) {
            alertHeading.textContent = "Critical overload risk detected";
        }

        if (alertMessage) {
            alertMessage.textContent =
                `${alerts.length} forecast hour(s) have predicted demand at or above ${CRITICAL_THRESHOLD} kW.`;
        }
    } else {
        banner?.classList.add("hidden");
    }

    // Forecast row count.
    const rowCount = document.getElementById("rowCount");

    if (rowCount) {
        rowCount.textContent =
            `${forecast.length} forecast hour${forecast.length === 1 ? "" : "s"}`;
    }

    // Forecast table.
    const rows = document.getElementById("forecastRows");

    if (rows) {
        rows.innerHTML = forecast.map(item => {
            const demand = Number(item.demand);
            const mode = item.mode || "Not available";
            const isCritical = demand >= CRITICAL_THRESHOLD;

            const status = item.alert ||
                (isCritical ? "Critical Overload" : "Normal");

            const statusClass =
                status.toLowerCase() === "normal"
                    ? "status-normal"
                    : "status-alert";

            const modeClass =
                mode.toLowerCase().includes("grid")
                    ? "mode-grid"
                    : "mode-storage";

            return `
                <tr>
                    <td>${escapeHTML(item.time ?? "--")}</td>
                    <td>${demand.toFixed(2)} kW</td>
                    <td class="${modeClass}">
                        ${escapeHTML(mode)}
                    </td>
                    <td class="${statusClass}">
                        ${escapeHTML(status)}
                    </td>
                </tr>
            `;
        }).join("");
    }

    renderChart();
}

// ==========================================
// DEMAND CHART
// ==========================================

function renderChart() {
    const canvas = document.getElementById("demandChart");

    if (!canvas) {
        console.error("Chart canvas #demandChart was not found.");
        return;
    }

    if (typeof window.Chart === "undefined") {
        console.error(
            "Chart.js did not load. Check your internet connection and index.html."
        );
        return;
    }

    const labels = forecast.map(item => item.time);
    const values = forecast.map(item => Number(item.demand));
    const thresholdValues = forecast.map(() => CRITICAL_THRESHOLD);

    const chartData = {
        labels,
        datasets: [
            {
                label: "Predicted demand",
                data: values,
                borderColor: "#34d399",
                backgroundColor: "rgba(52, 211, 153, 0.10)",
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                pointRadius: 3,
                pointHoverRadius: 6,
                pointBackgroundColor: "#34d399",
                pointBorderColor: "#101a2d"
            },
            {
                label: "Critical threshold (200 kW)",
                data: thresholdValues,
                borderColor: "#fb7185",
                borderWidth: 1.5,
                borderDash: [6, 5],
                pointRadius: 0,
                fill: false,
                tension: 0
            }
        ]
    };

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,

        interaction: {
            intersect: false,
            mode: "index"
        },

        plugins: {
            legend: {
                display: true,
                labels: {
                    color: "#cbd5e1",
                    usePointStyle: true,
                    padding: 16
                }
            },

            tooltip: {
                backgroundColor: "#152137",
                titleColor: "#f1f5f9",
                bodyColor: "#cbd5e1",
                borderColor: "#354762",
                borderWidth: 1,
                padding: 12,

                callbacks: {
                    label: context =>
                        `${context.dataset.label}: ${Number(context.raw).toFixed(2)} kW`
                }
            }
        },

        scales: {
            x: {
                title: {
                    display: true,
                    text: "Forecast time",
                    color: "#91a1b9",
                    font: { size: 11 }
                },

                ticks: {
                    color: "#91a1b9",
                    maxTicksLimit: 8,
                    maxRotation: 0
                },

                grid: {
                    color: "rgba(145, 161, 185, 0.08)"
                },

                border: {
                    color: "#24324a"
                }
            },

            y: {
                title: {
                    display: true,
                    text: "Demand (kW)",
                    color: "#91a1b9",
                    font: { size: 11 }
                },

                beginAtZero: false,

                ticks: {
                    color: "#91a1b9"
                },

                grid: {
                    color: "rgba(145, 161, 185, 0.10)"
                },

                border: {
                    color: "#24324a"
                }
            }
        }
    };

    if (demandChart) {
        demandChart.data = chartData;
        demandChart.options = chartOptions;
        demandChart.update();
    } else {
        demandChart = new window.Chart(canvas, {
            type: "line",
            data: chartData,
            options: chartOptions
        });
    }
}

// ==========================================
// HTML ESCAPING
// ==========================================

function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, character => {
        const entities = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        };

        return entities[character];
    });
}

// ==========================================
// CSV TELEMETRY UPLOAD
// ==========================================

async function uploadTelemetry(file) {
    const uploadStatus = document.getElementById("uploadStatus");
    const fileInput = document.getElementById("telemetryFile");

    if (!file) return;

    isUploading = true;

    if (uploadStatus) {
        uploadStatus.textContent = `Uploading ${file.name}...`;
    }

    if (fileInput) {
        fileInput.disabled = true;
    }

    try {
        if (!file.name.toLowerCase().endsWith(".csv")) {
            throw new Error("Please select a CSV file.");
        }

        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch("/api/upload-telemetry", {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "CSV upload failed.");
        }

        if (
            !Array.isArray(result.forecast) ||
            result.forecast.length === 0
        ) {
            throw new Error(
                "The uploaded CSV did not produce a forecast."
            );
        }

        forecast = result.forecast;
        usingUpload = true;

        // Read battery information from the upload response.
        batteryLevel = Number(
            result.battery_soc ??
            result.forecast[0].battery_soc ??
            78
        );

        batteryStatus =
            result.battery_status ??
            result.forecast[0].battery_status ??
            "Normal";

        if (!Number.isFinite(batteryLevel)) {
            batteryLevel = 78;
        }

        batteryLevel = Math.max(0, Math.min(100, batteryLevel));

        updateSourceBadge("CSV UPLOAD", false);
        renderDashboard();

        const updatedLabel = document.getElementById("updatedLabel");

        if (updatedLabel) {
            updatedLabel.textContent = "Updated from uploaded CSV";
        }

        if (uploadStatus) {
            uploadStatus.textContent =
                `Success! Processed ${result.rows_used ?? forecast.length} row(s) from ${file.name}.`;
        }

    } catch (error) {
        console.error("CSV upload failed:", error);

        if (uploadStatus) {
            uploadStatus.textContent =
                error.message || "Unable to upload CSV.";
        }

    } finally {
        isUploading = false;

        if (fileInput) {
            fileInput.disabled = false;
            fileInput.value = "";
        }
    }
}

// ==========================================
// INITIALIZE DASHBOARD
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
    const refreshButton = document.getElementById("refreshBtn");
    const fileInput = document.getElementById("telemetryFile");

    if (refreshButton) {
    refreshButton.addEventListener("click", () => {
        usingUpload = false;          // manual refresh goes back to live data
        loadForecast();
    });
}

    if (fileInput) {
        fileInput.addEventListener("change", event => {
            const file = event.target.files[0];

            if (file) {
                uploadTelemetry(file);
            }
        });
    }

    loadForecast();

    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    refreshTimer = setInterval(() => {
    if (!isUploading && !usingUpload) {
        loadForecast();
    }
}, REFRESH_INTERVAL);
});
