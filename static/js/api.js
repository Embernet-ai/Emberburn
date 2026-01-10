// EmberBurn API Client
// Handles all API communication with the backend

const API_BASE = '/api';

class EmberBurnAPI {
    constructor() {
        this.baseURL = API_BASE;
    }

    async fetchJSON(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, options);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        }
    }

    // Tag Methods
    async getTags() {
        return this.fetchJSON('/tags');
    }

    async getTag(tagName) {
        return this.fetchJSON(`/tags/${tagName}`);
    }

    async writeTag(tagName, value) {
        return this.fetchJSON(`/tags/${tagName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value })
        });
    }

    // Publisher Methods
    async getPublishers() {
        return this.fetchJSON('/publishers');
    }

    async togglePublisher(publisherName) {
        return this.fetchJSON(`/publishers/${publisherName}/toggle`, {
            method: 'POST'
        });
    }

    // Alarm Methods
    async getActiveAlarms() {
        return this.fetchJSON('/alarms/active');
    }

    // Health Check
    async healthCheck() {
        return this.fetchJSON('/health');
    }
}

// Create global API instance
window.api = new EmberBurnAPI();
