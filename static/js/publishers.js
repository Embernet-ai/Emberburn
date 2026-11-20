// Publishers View Logic

let publishersUpdater = null;

const PROTOCOL_ICONS = {
    'MQTT': '📨',
    'REST API': '🌐',
    'GraphQL': '🔷',
    'Sparkplug B': '⚡',
    'Kafka': '🎯',
    'AMQP': '🐰',
    'WebSocket': '🔌',
    'InfluxDB': '📊',
    'MODBUS TCP': '🔧',
    'EtherNet/IP': '🏭',
    'S7comm': '🏭',
    'BACnet/IP': '🏢',
    'DNP3': '⚡',
    'IEC 104': '⚡',
    'EtherNet/IP Client': '🏭',
    'OPC UA Client': '🔗',
    'Alarms': '🚨',
    'Prometheus': '📈',
    'SQLite Persistence': '💾',
    'Data Transformation': '🔀'
};

async function updatePublishersView() {
    try {
        const publishersData = await api.getPublishers();
        renderPublishersGrid(publishersData);
    } catch (error) {
        console.error('Publishers update error:', error);
    }
}

function renderPublishersGrid(publishersData) {
    const grid = document.getElementById('publishers-grid');
    const publishers = publishersData.publishers || [];

    if (publishers.length === 0) {
        grid.innerHTML = '<div class="card"><p style="text-align: center; color: var(--smoke-gray);">No publishers configured</p></div>';
        return;
    }

    grid.innerHTML = publishers.map(pub => `
        <div class="publisher-card">
            <div class="publisher-header">
                <div class="publisher-title">
                    <span class="publisher-icon">${PROTOCOL_ICONS[pub.name] || '📡'}</span>
                    ${escapeHTML(pub.name)}
                </div>
                <span class="status-badge ${pub.enabled ? 'status-active' : 'status-inactive'}">
                    ${pub.enabled ? 'ENABLED' : 'DISABLED'}
                </span>
            </div>
            <div class="publisher-description">
                ${escapeHTML(pub.description || 'Data publishing protocol')}
            </div>
            <div class="publisher-actions">
                <button class="btn ${pub.enabled ? 'btn-danger' : 'btn-success'}" 
                        onclick="togglePublisher('${escapeHTML(pub.name)}')">
                    ${pub.enabled ? '⏸️ Disable' : '▶️ Enable'}
                </button>
            </div>
        </div>
    `).join('');
}

async function togglePublisher(publisherName) {
    try {
        const result = await api.togglePublisher(publisherName);
        console.log('Toggle result:', result);
        // Immediately update the view
        await updatePublishersView();
    } catch (error) {
        console.error('Toggle publisher error:', error);
        alert('Failed to toggle publisher: ' + error.message);
    }
}

// Initialize publishers view
document.addEventListener('DOMContentLoaded', () => {
    publishersUpdater = new AutoUpdater(updatePublishersView, 2000);
    publishersUpdater.start();
});

// Cleanup
window.addEventListener('beforeunload', () => {
    if (publishersUpdater) publishersUpdater.stop();
});
