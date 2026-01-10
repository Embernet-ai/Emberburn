// EmberBurn Core Application Logic

// Utility Functions
function formatTimestamp(timestamp) {
    return new Date(timestamp * 1000).toLocaleString();
}

function formatTimeOnly(timestamp) {
    return new Date(timestamp * 1000).toLocaleTimeString();
}

function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Auto-update Manager
class AutoUpdater {
    constructor(updateFunction, interval = 2000) {
        this.updateFunction = updateFunction;
        this.interval = interval;
        this.intervalId = null;
        this.isRunning = false;
    }

    start() {
        if (this.isRunning) return;
        this.isRunning = true;
        
        // Run immediately
        this.updateFunction();
        
        // Then set interval
        this.intervalId = setInterval(() => {
            this.updateFunction();
        }, this.interval);
    }

    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.isRunning = false;
    }

    restart() {
        this.stop();
        this.start();
    }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('🔥 EmberBurn Web UI Initialized');
});
