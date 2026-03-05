/**
 * MCP Feedback - Session Switcher Module
 * =======================================
 * Manages multi-session sidebar list and Lobby WebSocket connection.
 */

(function() {
    'use strict';

    window.MCPFeedback = window.MCPFeedback || {};

    function SessionSwitcher(options) {
        options = options || {};

        this.sessions = [];
        this.activeSessionId = null;

        // Use sidebar session list as primary container
        this.containerEl = document.getElementById('sidebarSessionList')
                        || document.getElementById('sessionTabsContainer');

        this.lobbyWs = null;
        this.lobbyReconnectTimer = null;
        this.lobbyReconnectDelay = 2000;

        this.onSwitch = options.onSwitch || null;
        this.onNewSession = options.onNewSession || null;

        this._boundOnBeforeUnload = this._cleanup.bind(this);
        window.addEventListener('beforeunload', this._boundOnBeforeUnload);
    }

    SessionSwitcher.prototype.init = function() {
        this.connectLobby();
    };

    // ===== Lobby WebSocket =====

    SessionSwitcher.prototype.connectLobby = function() {
        if (this.lobbyWs) {
            try { this.lobbyWs.close(); } catch (e) { /* ignore */ }
        }

        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var url = protocol + '//' + window.location.host + '/ws/lobby';
        var self = this;

        this.lobbyWs = new WebSocket(url);

        this.lobbyWs.onopen = function() {
            console.log('[SessionSwitcher] Lobby connected');
            self.lobbyReconnectDelay = 2000;
        };

        this.lobbyWs.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                self._handleLobbyMessage(data);
            } catch (e) {
                console.error('[SessionSwitcher] Parse error:', e);
            }
        };

        this.lobbyWs.onclose = function() {
            self._scheduleLobbyReconnect();
        };

        this.lobbyWs.onerror = function(err) {
            console.error('[SessionSwitcher] Lobby error:', err);
        };

        this._startLobbyHeartbeat();
    };

    SessionSwitcher.prototype._scheduleLobbyReconnect = function() {
        var self = this;
        if (this.lobbyReconnectTimer) return;

        this.lobbyReconnectTimer = setTimeout(function() {
            self.lobbyReconnectTimer = null;
            self.connectLobby();
        }, this.lobbyReconnectDelay);

        this.lobbyReconnectDelay = Math.min(this.lobbyReconnectDelay * 1.5, 30000);
    };

    SessionSwitcher.prototype._startLobbyHeartbeat = function() {
        var self = this;
        if (this._lobbyHeartbeatTimer) clearInterval(this._lobbyHeartbeatTimer);

        this._lobbyHeartbeatTimer = setInterval(function() {
            if (self.lobbyWs && self.lobbyWs.readyState === WebSocket.OPEN) {
                self.lobbyWs.send(JSON.stringify({
                    type: 'heartbeat',
                    timestamp: Date.now()
                }));
            }
        }, 15000);
    };

    SessionSwitcher.prototype._handleLobbyMessage = function(data) {
        switch (data.type) {
            case 'sessions_list':
                this._setSessions(data.sessions || []);
                break;
            case 'new_session':
                this._addSession(data.session_info);
                break;
            case 'session_changed':
                this._updateSessionStatus(data.session_info);
                break;
            case 'heartbeat_response':
                break;
        }
    };

    // ===== Session Data =====

    SessionSwitcher.prototype._setSessions = function(sessions) {
        this.sessions = sessions;

        if (sessions.length > 0 && !this.activeSessionId) {
            var waiting = sessions.filter(function(s) { return s.status === 'waiting'; });
            this.activeSessionId = waiting.length > 0
                ? waiting[waiting.length - 1].session_id
                : sessions[sessions.length - 1].session_id;
        }

        this._render();
    };

    SessionSwitcher.prototype._addSession = function(info) {
        if (!info || !info.session_id) return;

        var exists = this.sessions.some(function(s) {
            return s.session_id === info.session_id;
        });

        if (!exists) {
            this.sessions.push(info);
        }

        var wasAlreadyActive = (this.activeSessionId === info.session_id);
        this.activeSessionId = info.session_id;
        this._render();

        if (!wasAlreadyActive && this.onNewSession) {
            this.onNewSession(info);
        }
    };

    SessionSwitcher.prototype._updateSessionStatus = function(info) {
        if (!info || !info.session_id) return;

        for (var i = 0; i < this.sessions.length; i++) {
            if (this.sessions[i].session_id === info.session_id) {
                this.sessions[i].status = info.status;
                if (info.title !== undefined) {
                    this.sessions[i].title = info.title;
                }
                break;
            }
        }

        this._render();
    };

    SessionSwitcher.prototype._removeSession = function(sessionId) {
        this.sessions = this.sessions.filter(function(s) {
            return s.session_id !== sessionId;
        });

        if (this.activeSessionId === sessionId) {
            var waiting = this.sessions.filter(function(s) { return s.status === 'waiting'; });
            if (waiting.length > 0) {
                this.activeSessionId = waiting[waiting.length - 1].session_id;
            } else if (this.sessions.length > 0) {
                this.activeSessionId = this.sessions[this.sessions.length - 1].session_id;
            } else {
                this.activeSessionId = null;
            }

            if (this.activeSessionId && this.onSwitch) {
                this.onSwitch(this.activeSessionId);
            }
        }

        this._render();
    };

    // ===== Render (Sidebar Style) =====

    SessionSwitcher.prototype._getSortedSessions = function() {
        var statusOrder = { 'waiting': 0, 'active': 1, 'feedback_submitted': 2, 'completed': 3, 'timeout': 4, 'error': 5 };
        return this.sessions.slice().sort(function(a, b) {
            var oa = statusOrder[a.status] !== undefined ? statusOrder[a.status] : 9;
            var ob = statusOrder[b.status] !== undefined ? statusOrder[b.status] : 9;
            if (oa !== ob) return oa - ob;
            return 0;
        });
    };

    SessionSwitcher.prototype._render = function() {
        if (!this.containerEl) return;

        var self = this;
        this.containerEl.innerHTML = '';
        var sorted = this._getSortedSessions();

        sorted.forEach(function(session) {
            var status = session.status || 'waiting';
            var isActive = session.session_id === self.activeSessionId;
            var isWaiting = status === 'waiting';

            var item = document.createElement('div');
            item.className = 'session-item' + (isActive ? ' active' : '') + (isWaiting ? ' waiting-state' : '');
            item.dataset.sessionId = session.session_id;

            var textGroup = document.createElement('div');
            textGroup.className = 'session-text-group';

            var label = document.createElement('span');
            label.className = 'session-label';
            label.textContent = session.title || session.session_id.substring(0, 8);
            textGroup.appendChild(label);

            if (isWaiting) {
                var badge = document.createElement('span');
                badge.className = 'session-waiting-badge';
                badge.textContent = '\u7B49\u5F85\u4E2D';
                textGroup.appendChild(badge);
            }

            item.appendChild(textGroup);

            item.title = (session.title || session.session_id) + ' (' + status + ')';

            item.addEventListener('click', function() {
                if (self.activeSessionId !== session.session_id) {
                    self.activeSessionId = session.session_id;
                    self._render();
                    if (self.onSwitch) {
                        self.onSwitch(session.session_id);
                    }
                }
            });

            self.containerEl.appendChild(item);
        });
    };

    SessionSwitcher.prototype.getActiveSessionId = function() {
        return this.activeSessionId;
    };

    SessionSwitcher.prototype.setActiveSessionId = function(sessionId) {
        this.activeSessionId = sessionId;
        this._render();
    };

    SessionSwitcher.prototype._cleanup = function() {
        if (this._lobbyHeartbeatTimer) clearInterval(this._lobbyHeartbeatTimer);
        if (this.lobbyReconnectTimer) clearTimeout(this.lobbyReconnectTimer);
        if (this.lobbyWs) {
            try { this.lobbyWs.close(); } catch (e) { /* ignore */ }
        }
    };

    SessionSwitcher.prototype.destroy = function() {
        window.removeEventListener('beforeunload', this._boundOnBeforeUnload);
        this._cleanup();
    };

    window.MCPFeedback.SessionSwitcher = SessionSwitcher;
    console.log('[SessionSwitcher] Module loaded');
})();
