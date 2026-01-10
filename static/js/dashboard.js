// Dashboard View Logic

let dashboardUpdater = null;

async function updateDashboard() {
    try {
        // Fetch all data in parallel
        const [tagsData, publishersData, alarmsData] = await Promise.all([
            api.getTags(),
            api.getPublishers(),
            api.getActiveAlarms()
        ]);

        // Update metric cards
        updateMetricCards(tagsData, publishersData, alarmsData);

        // Update live tags table
        updateLiveTagsTable(tagsData);

    } catch (error) {
        console.error('Dashboard update error:', error);
    }
}

function updateMetricCards(tagsData, publishersData, alarmsData) {
    // Active Tags
    const activeTags = Object.keys(tagsData.tags || {}).length;
    document.getElementById('active-tags-count').textContent = activeTags;

    // Publishers
    const publishers = publishersData.publishers || [];
    const enabledCount = publishers.filter(p => p.enabled).length;
    document.getElementById('publishers-count').textContent = `${enabledCount} / ${publishers.length}`;

    // Alarms
    const alarms = alarmsData.alarms || [];
    const criticalAlarms = alarms.filter(a => a.priority === 'CRITICAL').length;
    const alarmsCountEl = document.getElementById('alarms-count');
    alarmsCountEl.textContent = alarms.length;
    alarmsCountEl.style.color = criticalAlarms > 0 ? 'var(--error-red)' : 'var(--success-green)';
    
    document.getElementById('critical-count').textContent = `${criticalAlarms} critical`;
}

function updateLiveTagsTable(tagsData) {
    const tbody = document.getElementById('live-tags-table');
    const tags = tagsData.tags || {};
    const tagEntries = Object.entries(tags).slice(0, 10); // Show top 10

    if (tagEntries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading">No tags available</td></tr>';
        return;
    }

    tbody.innerHTML = tagEntries.map(([name, data]) => `
        <tr>
            <td style="font-weight: bold;">${escapeHTML(name)}</td>
            <td style="color: var(--fire-yellow); font-size: 18px;">${escapeHTML(String(data.value))}</td>
            <td>${formatTimeOnly(data.timestamp)}</td>
            <td><span class="status-badge status-active pulse">LIVE</span></td>
        </tr>
    `).join('');
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    dashboardUpdater = new AutoUpdater(updateDashboard, 2000);
    dashboardUpdater.start();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (dashboardUpdater) {
        dashboardUpdater.stop();
    }
});
