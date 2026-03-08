(function () {
  const root = document.getElementById('rbt-nf-dashboard');
  if (!root) {
    return;
  }

  const config = window.RBTNorthflankStatsConfig || {};
  const endpoint = config.endpoint || 'https://rbtproject.up.railway.app/api/northflank/stats/';
  const refreshIntervalMs = Number(config.refreshIntervalMs || 300000);

  const state = {
    charts: {},
    timer: null,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const node = el(id);
    if (node) {
      node.textContent = value;
    }
  }

  function showWarning(message) {
    const warning = el('nf-warning');
    if (!warning) {
      return;
    }
    warning.hidden = false;
    warning.textContent = message;
  }

  function hideWarning() {
    const warning = el('nf-warning');
    if (!warning) {
      return;
    }
    warning.hidden = true;
    warning.textContent = '';
  }

  function labelsAndValues(points) {
    return {
      labels: (points || []).map((p) => p.label || 'unknown'),
      values: (points || []).map((p) => Number(p.value || 0)),
    };
  }

  function createOrUpdateChart(chartKey, canvasId, type, chartData, options) {
    const canvas = el(canvasId);
    if (!canvas || !window.Chart) {
      return;
    }
    const ctx = canvas.getContext('2d');

    if (state.charts[chartKey]) {
      state.charts[chartKey].data = chartData;
      state.charts[chartKey].options = options;
      state.charts[chartKey].update();
      return;
    }

    state.charts[chartKey] = new Chart(ctx, {
      type,
      data: chartData,
      options,
    });
  }

  function renderSummary(summary) {
    setText('nf-services-total', summary.services_total ?? 0);
    setText('nf-addons-total', summary.addons_total ?? 0);
    setText('nf-uptime-ratio', `${Math.round(Number(summary.uptime_ratio || 0) * 100)}%`);

    const runningUnits = Number(summary.running_services || 0) + Number(summary.running_addons || 0);
    setText('nf-running-units', runningUnits);
  }

  function renderCapacity(compute) {
    const cap = ((compute || {}).capacity_totals) || {};
    const node = el('nf-capacity');
    if (!node) {
      return;
    }

    node.innerHTML = `
      <div class="rbt-nf-capacity-item"><span>Instances</span><strong>${Number(cap.instances || 0).toFixed(2)}</strong></div>
      <div class="rbt-nf-capacity-item"><span>CPU Units</span><strong>${Number(cap.cpu || 0).toFixed(2)}</strong></div>
      <div class="rbt-nf-capacity-item"><span>Memory Units</span><strong>${Number(cap.memory || 0).toFixed(2)}</strong></div>
    `;
  }

  function renderCosts(costs) {
    const node = el('nf-costs');
    if (!node) {
      return;
    }

    if (!costs || !costs.available) {
      node.textContent = 'Cost data is not currently available from the configured Northflank CLI command.';
      return;
    }

    node.textContent = JSON.stringify(costs.data, null, 2);
  }

  function renderMeta(meta) {
    const node = el('nf-meta');
    if (!node) {
      return;
    }
    const ts = meta.generated_at || '--';
    const project = meta.project_id || '--';
    node.textContent = `Project: ${project} • Last update: ${ts}`;
  }

  function renderCharts(chartData) {
    const serviceStatus = labelsAndValues(chartData.service_status_pie);
    const addonStatus = labelsAndValues(chartData.addon_status_pie);
    const serviceTypes = labelsAndValues(chartData.service_types_bar);
    const regions = labelsAndValues(chartData.reach_regions_bar);
    const series = chartData.uptime_downtime_timeseries || [];

    createOrUpdateChart(
      'serviceStatus',
      'nf-service-status-chart',
      'doughnut',
      {
        labels: serviceStatus.labels,
        datasets: [{ data: serviceStatus.values }],
      },
      { responsive: true, maintainAspectRatio: false }
    );

    createOrUpdateChart(
      'addonStatus',
      'nf-addon-status-chart',
      'doughnut',
      {
        labels: addonStatus.labels,
        datasets: [{ data: addonStatus.values }],
      },
      { responsive: true, maintainAspectRatio: false }
    );

    createOrUpdateChart(
      'serviceTypes',
      'nf-service-types-chart',
      'bar',
      {
        labels: serviceTypes.labels,
        datasets: [{ label: 'Services', data: serviceTypes.values }],
      },
      {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true } },
      }
    );

    createOrUpdateChart(
      'regions',
      'nf-regions-chart',
      'bar',
      {
        labels: regions.labels,
        datasets: [{ label: 'Regions', data: regions.values }],
      },
      {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true } },
      }
    );

    createOrUpdateChart(
      'uptime',
      'nf-uptime-chart',
      'line',
      {
        labels: series.map((p) => (p.timestamp || '').replace('T', ' ').replace('Z', '')),
        datasets: [
          { label: 'Running Services', data: series.map((p) => Number(p.running_services || 0)) },
          { label: 'Paused Services', data: series.map((p) => Number(p.paused_services || 0)) },
          { label: 'Running Addons', data: series.map((p) => Number(p.running_addons || 0)) },
          { label: 'Paused Addons', data: series.map((p) => Number(p.paused_addons || 0)) },
        ],
      },
      {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true } },
      }
    );
  }

  async function fetchAndRender(forceRefresh) {
    try {
      const url = new URL(endpoint);
      if (forceRefresh) {
        url.searchParams.set('refresh', '1');
      }
      url.searchParams.set('lookback_hours', '24');

      const response = await fetch(url.toString(), { method: 'GET' });
      if (!response.ok) {
        throw new Error(`Failed with status ${response.status}`);
      }

      const data = await response.json();
      renderSummary(data.summary || {});
      renderCapacity(data.compute || {});
      renderCosts(data.costs || {});
      renderMeta(data.meta || {});
      renderCharts(data.chart_data || {});

      if (Array.isArray(data.warnings) && data.warnings.length) {
        showWarning(data.warnings.join(' | '));
      } else {
        hideWarning();
      }
    } catch (error) {
      showWarning(`Could not load Northflank stats: ${error.message}`);
    }
  }

  const refreshBtn = el('rbt-nf-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function () {
      fetchAndRender(true);
    });
  }

  fetchAndRender(false);

  if (refreshIntervalMs > 0) {
    state.timer = setInterval(function () {
      fetchAndRender(false);
    }, refreshIntervalMs);
  }
})();
