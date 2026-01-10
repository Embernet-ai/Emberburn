// Tags View Logic

let tagsUpdater = null;

async function updateTagsView() {
    try {
        const tagsData = await api.getTags();
        renderTagsTable(tagsData);
    } catch (error) {
        console.error('Tags update error:', error);
    }
}

function renderTagsTable(tagsData) {
    const tbody = document.getElementById('tags-table');
    const tags = tagsData.tags || {};
    const tagEntries = Object.entries(tags);

    if (tagEntries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="loading">No tags available</td></tr>';
        return;
    }

    tbody.innerHTML = tagEntries.map(([name, data]) => `
        <tr>
            <td style="font-weight: bold;">${escapeHTML(name)}</td>
            <td style="color: var(--fire-yellow); font-size: 18px;">${escapeHTML(String(data.value))}</td>
            <td>${typeof data.value}</td>
            <td>${formatTimestamp(data.timestamp)}</td>
            <td>
                <button class="btn btn-secondary" style="padding: 5px 10px; font-size: 12px;" 
                        onclick="alert('History view coming soon!')">
                    📊 History
                </button>
            </td>
        </tr>
    `).join('');
}

// Initialize tags view
document.addEventListener('DOMContentLoaded', () => {
    tagsUpdater = new AutoUpdater(updateTagsView, 2000);
    tagsUpdater.start();
});

// Cleanup
window.addEventListener('beforeunload', () => {
    if (tagsUpdater) tagsUpdater.stop();
});
