/**
 * MCP Feedback Enhanced - 會話切換器模組
 * ======================================
 *
 * 管理多會話並發的標籤欄 UI 和 Lobby WebSocket 連接。
 * 透過 Lobby 頻道接收新會話通知和狀態變更。
 */

(function() {
    'use strict';

    window.MCPFeedback = window.MCPFeedback || {};

    function SessionSwitcher(options) {
        options = options || {};

        this.sessions = [];
        this.activeSessionId = null;

        this.barEl = document.getElementById('sessionSwitcherBar');
        this.containerEl = document.getElementById('sessionTabsContainer');

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

        console.log('[SessionSwitcher] 連接 Lobby:', url);
        this.lobbyWs = new WebSocket(url);

        this.lobbyWs.onopen = function() {
            console.log('[SessionSwitcher] Lobby 連接成功');
            self.lobbyReconnectDelay = 2000;
        };

        this.lobbyWs.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                self._handleLobbyMessage(data);
            } catch (e) {
                console.error('[SessionSwitcher] 解析 Lobby 消息失敗:', e);
            }
        };

        this.lobbyWs.onclose = function() {
            console.log('[SessionSwitcher] Lobby 連接關閉，準備重連');
            self._scheduleLobbyReconnect();
        };

        this.lobbyWs.onerror = function(err) {
            console.error('[SessionSwitcher] Lobby 錯誤:', err);
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
            default:
                console.log('[SessionSwitcher] 未知 Lobby 消息:', data.type);
        }
    };

    // ===== 會話數據管理 =====

    SessionSwitcher.prototype._setSessions = function(sessions) {
        this.sessions = sessions;

        if (sessions.length > 0 && !this.activeSessionId) {
            var waiting = sessions.filter(function(s) { return s.status === 'waiting'; });
            this.activeSessionId = waiting.length > 0
                ? waiting[waiting.length - 1].session_id
                : sessions[sessions.length - 1].session_id;
        }

        this._render();
        this._updateBarVisibility();
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
        this._updateBarVisibility();

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
        this._updateBarVisibility();
    };

    // ===== 渲染 =====

    SessionSwitcher.prototype._updateBarVisibility = function() {
        if (!this.barEl) return;
        this.barEl.style.display = 'flex';
    };

    SessionSwitcher.prototype._render = function() {
        if (!this.containerEl) return;

        var self = this;
        this.containerEl.innerHTML = '';

        this.sessions.forEach(function(session) {
            var tab = document.createElement('div');
            tab.className = 'session-tab' + (session.session_id === self.activeSessionId ? ' active' : '');
            tab.dataset.sessionId = session.session_id;

            var statusDot = document.createElement('span');
            statusDot.className = 'tab-status ' + (session.status || 'waiting');
            tab.appendChild(statusDot);

            var label = document.createElement('span');
            label.className = 'tab-label';
            var name = session.title || session.session_id.substring(0, 8);
            label.textContent = name;
            label.title = (session.title || session.session_id) + ' (' + (session.status || 'waiting') + ')';
            tab.appendChild(label);

            var closeBtn = document.createElement('span');
            closeBtn.className = 'tab-close';
            closeBtn.textContent = '\u00d7';
            closeBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                self._removeSession(session.session_id);
            });
            tab.appendChild(closeBtn);

            tab.addEventListener('click', function() {
                if (self.activeSessionId !== session.session_id) {
                    self.activeSessionId = session.session_id;
                    self._render();
                    if (self.onSwitch) {
                        self.onSwitch(session.session_id);
                    }
                }
            });

            self.containerEl.appendChild(tab);
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
    console.log('[SessionSwitcher] 模組載入完成');
})();
