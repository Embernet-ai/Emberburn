// Alarms View Logic

let alarmsUpdater = null;

async function updateAlarmsView() {
    try {
        const alarmsData = await api.getActiveAlarms();
        renderAlarmsView(alarmsData);
    } catch (error) {
        console.error('Alarms update error:', error);
    }
}

function renderAlarmsView(alarmsData) {
    const container = document.getElementById('alarms-container');
    const alarms = alarmsData.alarms || [];

    if (alarms.length === 0) {
        container.innerHTML = `
            <div class="card empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>All Systems Normal</h2>
                <p>No active alarms</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Alarm</th>
                        <th>Tag</th>
                        <th>Value</th>
                        <th>Message</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    ${alarms.map(alarm => `
                        <tr>
                            <td>
                                <span class="status-badge status-${alarm.priority.toLowerCase()}">
                                    ${escapeHTML(alarm.priority)}
                                </span>
                            </td>
                            <td style="font-weight: bold;">${escapeHTML(alarm.rule_name)}</td>
                            <td>${escapeHTML(alarm.tag)}</td>
                            <td style="color: var(--fire-yellow);">${escapeHTML(String(alarm.triggered_value))}</td>
                            <td>${escapeHTML(alarm.message)}</td>
                            <td>${formatTimestamp(alarm.triggered_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// Initialize alarms view
document.addEventListener('DOMContentLoaded', () => {
    alarmsUpdater = new AutoUpdater(updateAlarmsView, 2000);
    alarmsUpdater.start();
});

// Cleanup
window.addEventListener('beforeunload', () => {
    if (alarmsUpdater) alarmsUpdater.stop();
});
