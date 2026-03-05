/**
 * MCP Feedback - UI Manager Module
 * =================================
 * Handles sidebar navigation, panel switching, chat rendering, and feedback state
 */

(function() {
    'use strict';

    window.MCPFeedback = window.MCPFeedback || {};
    var Utils = window.MCPFeedback.Utils;

    function UIManager(options) {
        options = options || {};

        this.currentTab = options.currentTab || 'combined';
        this.feedbackState = Utils.CONSTANTS.FEEDBACK_WAITING;
        this.layoutMode = options.layoutMode || 'combined-vertical';
        this.lastSubmissionTime = null;

        this.connectionIndicator = null;
        this.connectionText = null;
        this.tabButtons = null;
        this.tabContents = null;
        this.submitBtn = null;
        this.rightPanel = null;

        this.onTabChange = options.onTabChange || null;
        this.onLayoutModeChange = options.onLayoutModeChange || null;

        this.initDebounceHandlers();
        this.initUIElements();
    }

    UIManager.prototype.initDebounceHandlers = function() {
        this._debouncedUpdateStatusIndicator = Utils.DOM.debounce(
            this._originalUpdateStatusIndicator.bind(this),
            100,
            false
        );

        this._debouncedUpdateStatusIndicatorElement = Utils.DOM.debounce(
            this._originalUpdateStatusIndicatorElement.bind(this),
            50,
            false
        );
    };

    UIManager.prototype.initUIElements = function() {
        this.connectionIndicator = Utils.safeQuerySelector('#connectionIndicator');
        this.connectionText = Utils.safeQuerySelector('#connectionText');
        this.tabButtons = document.querySelectorAll('.tab-button');
        this.tabContents = document.querySelectorAll('.tab-content');
        this.submitBtn = Utils.safeQuerySelector('#submitBtn');
        this.rightPanel = Utils.safeQuerySelector('#rightPanel');

        console.log('UI elements initialized');
    };

    UIManager.prototype.initTabs = function() {
        var self = this;

        this.tabButtons.forEach(function(button) {
            button.addEventListener('click', function() {
                var tabName = button.getAttribute('data-tab');
                self.switchTab(tabName);
            });
        });

        var initialTab = this.currentTab;
        if (this.layoutMode.startsWith('combined')) {
            initialTab = 'combined';
        } else if (this.currentTab === 'combined') {
            initialTab = 'feedback';
        }

        this.setInitialTab(initialTab);
    };

    UIManager.prototype.setInitialTab = function(tabName) {
        this.currentTab = tabName;
        this.updateTabDisplay(tabName);
        this.handleSpecialTabs(tabName);
    };

    UIManager.prototype.switchTab = function(tabName) {
        this.currentTab = tabName;
        this.updateTabDisplay(tabName);
        this.handleSpecialTabs(tabName);

        if (this.onTabChange) {
            this.onTabChange(tabName);
        }
    };

    UIManager.prototype.updateTabDisplay = function(tabName) {
        this.tabButtons.forEach(function(button) {
            if (button.getAttribute('data-tab') === tabName) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });

        this.tabContents.forEach(function(content) {
            if (content.id === 'tab-' + tabName) {
                content.classList.add('active');
            } else {
                content.classList.remove('active');
            }
        });

        // Toggle right panel: visible only for workspace view
        if (this.rightPanel) {
            if (tabName === 'combined') {
                this.rightPanel.classList.remove('hidden');
            } else {
                this.rightPanel.classList.add('hidden');
            }
        }
    };

    UIManager.prototype.handleSpecialTabs = function(tabName) {
        if (tabName === 'combined') {
            this.handleCombinedMode();
        }
    };

    UIManager.prototype.handleCombinedMode = function() {
        // Three-column layout is always active in workspace mode
    };

    UIManager.prototype.updateTabVisibility = function() {
        // In the new sidebar layout, all nav items are always visible
        var summaryTab = document.querySelector('.tab-button[data-tab="summary"]');
        if (summaryTab) summaryTab.style.display = 'none';
    };

    UIManager.prototype.setFeedbackState = function(state, sessionId) {
        this.feedbackState = state;
        this.updateUIState();
        this.updateStatusIndicator();
    };

    UIManager.prototype.updateUIState = function() {
        this.updateSubmitButton();
        this.updateFeedbackInputs();
        this.updateImageUploadAreas();
    };

    UIManager.prototype.updateSubmitButton = function() {
        var submitButtons = [
            Utils.safeQuerySelector('#submitBtn')
        ].filter(function(btn) { return btn !== null; });

        var self = this;
        submitButtons.forEach(function(button) {
            if (!button) return;

            switch (self.feedbackState) {
                case Utils.CONSTANTS.FEEDBACK_WAITING:
                    button.textContent = window.i18nManager ? window.i18nManager.t('buttons.submit') : '提交反馈';
                    button.className = 'submit-btn btn-primary';
                    button.disabled = false;
                    break;
                case Utils.CONSTANTS.FEEDBACK_PROCESSING:
                    button.textContent = window.i18nManager ? window.i18nManager.t('buttons.processing') : '处理中...';
                    button.className = 'submit-btn btn-secondary';
                    button.disabled = true;
                    break;
                case Utils.CONSTANTS.FEEDBACK_SUBMITTED:
                    button.textContent = window.i18nManager ? window.i18nManager.t('buttons.submitted') : '已提交';
                    button.className = 'submit-btn btn-success';
                    button.disabled = true;
                    break;
            }
        });
    };

    UIManager.prototype.updateFeedbackInputs = function() {
        var feedbackInput = Utils.safeQuerySelector('#combinedFeedbackText');
        var canInput = this.feedbackState === Utils.CONSTANTS.FEEDBACK_WAITING;
        if (feedbackInput) {
            feedbackInput.disabled = !canInput;
        }
    };

    UIManager.prototype.updateImageUploadAreas = function() {
        var uploadAreas = [
            Utils.safeQuerySelector('#feedbackImageUploadArea'),
            Utils.safeQuerySelector('#combinedImageUploadArea')
        ].filter(function(area) { return area !== null; });

        var canUpload = this.feedbackState === Utils.CONSTANTS.FEEDBACK_WAITING;
        uploadAreas.forEach(function(area) {
            if (canUpload) {
                area.classList.remove('disabled');
            } else {
                area.classList.add('disabled');
            }
        });
    };

    UIManager.prototype._originalUpdateStatusIndicator = function() {
        var feedbackStatusIndicator = Utils.safeQuerySelector('#feedbackStatusIndicator');
        var combinedStatusIndicator = Utils.safeQuerySelector('#combinedFeedbackStatusIndicator');
        var statusInfo = this.getStatusInfo();

        if (feedbackStatusIndicator) {
            this._originalUpdateStatusIndicatorElement(feedbackStatusIndicator, statusInfo);
        }
        if (combinedStatusIndicator) {
            this._originalUpdateStatusIndicatorElement(combinedStatusIndicator, statusInfo);
        }

        if (!this._lastStatusInfo || this._lastStatusInfo.status !== statusInfo.status) {
            this._lastStatusInfo = statusInfo;
        }
    };

    UIManager.prototype.updateStatusIndicator = function() {
        if (this._debouncedUpdateStatusIndicator) {
            this._debouncedUpdateStatusIndicator();
        } else {
            this._originalUpdateStatusIndicator();
        }
    };

    UIManager.prototype.getStatusInfo = function() {
        var icon, title, message, status;

        switch (this.feedbackState) {
            case Utils.CONSTANTS.FEEDBACK_WAITING:
                icon = '';
                title = window.i18nManager ? window.i18nManager.t('status.waiting.title') : '等待反馈';
                message = window.i18nManager ? window.i18nManager.t('status.waiting.message') : '请提供您的反馈';
                status = 'waiting';
                break;
            case Utils.CONSTANTS.FEEDBACK_PROCESSING:
                icon = '';
                title = window.i18nManager ? window.i18nManager.t('status.processing.title') : '处理中';
                message = window.i18nManager ? window.i18nManager.t('status.processing.message') : '正在提交...';
                status = 'processing';
                break;
            case Utils.CONSTANTS.FEEDBACK_SUBMITTED:
                var timeStr = this.lastSubmissionTime ? new Date(this.lastSubmissionTime).toLocaleTimeString() : '';
                icon = '';
                title = window.i18nManager ? window.i18nManager.t('status.submitted.title') : '已提交';
                message = window.i18nManager ? window.i18nManager.t('status.submitted.message') : '等待下次调用';
                if (timeStr) message += ' (' + timeStr + ')';
                status = 'submitted';
                break;
            default:
                icon = '';
                title = '等待反馈';
                message = '请提供您的反馈';
                status = 'waiting';
        }

        return { icon: icon, title: title, message: message, status: status };
    };

    UIManager.prototype._originalUpdateStatusIndicatorElement = function(element, statusInfo) {
        if (!element) return;
        element.className = 'feedback-status-indicator status-' + statusInfo.status;
        element.style.display = 'block';

        var titleElement = element.querySelector('.status-title');
        if (titleElement) {
            titleElement.textContent = statusInfo.title;
        }

        var messageElement = element.querySelector('.status-message');
        if (messageElement) {
            messageElement.textContent = statusInfo.message;
        }
    };

    UIManager.prototype.updateStatusIndicatorElement = function(element, statusInfo) {
        if (this._debouncedUpdateStatusIndicatorElement) {
            this._debouncedUpdateStatusIndicatorElement(element, statusInfo);
        } else {
            this._originalUpdateStatusIndicatorElement(element, statusInfo);
        }
    };

    UIManager.prototype.updateConnectionStatus = function(status, text) {
        if (this.connectionIndicator) {
            this.connectionIndicator.className = 'connection-indicator ' + status;
        }
        if (this.connectionText) {
            this.connectionText.textContent = text;
        }
    };

    UIManager.prototype.renderMarkdownSafely = function(content) {
        try {
            if (typeof window.marked === 'undefined' || typeof window.DOMPurify === 'undefined') {
                return this.escapeHtml(content);
            }
            var htmlContent = window.marked.parse(content);
            var cleanHtml = window.DOMPurify.sanitize(htmlContent, {
                ALLOWED_TAGS: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'strong', 'em', 'code', 'pre', 'ul', 'ol', 'li', 'blockquote', 'a', 'hr', 'del', 's', 'table', 'thead', 'tbody', 'tr', 'td', 'th'],
                ALLOWED_ATTR: ['href', 'title', 'class', 'align', 'style'],
                ALLOW_DATA_ATTR: false
            });
            return cleanHtml;
        } catch (error) {
            console.error('Markdown render failed:', error);
            return this.escapeHtml(content);
        }
    };

    UIManager.prototype.escapeHtml = function(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    /**
     * Render AI summary content as chat messages
     */
    UIManager.prototype.updateAISummaryContent = function(summary, messageHistory) {
        if (messageHistory && messageHistory.length > 0) {
            this._renderConversationHistory(messageHistory);
            return;
        }

        var renderedContent = this.renderMarkdownSafely(summary);

        // Build a single AI message in chat format
        var html = '<div class="chat-message msg-assistant">';
        html += '<div class="chat-avatar ai">Ai</div>';
        html += '<div class="chat-body">';
        html += '<div class="chat-role">AI Assistant</div>';
        html += '<div class="chat-content">' + renderedContent + '</div>';
        html += '</div></div>';

        var summaryContent = Utils.safeQuerySelector('#summaryContent');
        if (summaryContent) {
            summaryContent.innerHTML = html;
            this.enhanceChatContent(summaryContent);
        }

        var combinedSummaryContent = Utils.safeQuerySelector('#combinedSummaryContent');
        if (combinedSummaryContent) {
            combinedSummaryContent.innerHTML = html;
            this.enhanceChatContent(combinedSummaryContent);
            combinedSummaryContent.scrollTop = combinedSummaryContent.scrollHeight;
        }
    };

    UIManager.prototype.appendUserMessage = function(content, images) {
        var renderedContent = this.renderMarkdownSafely(content);
        var msgHtml = '<div class="chat-message msg-user">';
        msgHtml += '<div class="chat-avatar user">You</div>';
        msgHtml += '<div class="chat-body">';
        msgHtml += '<div class="chat-role">You</div>';
        msgHtml += '<div class="chat-content">' + renderedContent;

        if (images && images.length > 0) {
            msgHtml += this._renderChatImages(images);
        }

        msgHtml += '</div></div></div>';

        var containers = [
            Utils.safeQuerySelector('#summaryContent .conversation-history'),
            Utils.safeQuerySelector('#combinedSummaryContent .conversation-history')
        ];

        if (!containers[0] && !containers[1]) {
            containers = [
                Utils.safeQuerySelector('#summaryContent'),
                Utils.safeQuerySelector('#combinedSummaryContent')
            ];
        }

        for (var i = 0; i < containers.length; i++) {
            if (containers[i]) {
                containers[i].insertAdjacentHTML('beforeend', msgHtml);
                this.enhanceChatContent(containers[i]);
                containers[i].scrollTop = containers[i].scrollHeight;
            }
        }
    };

    UIManager.prototype._renderChatImages = function(images) {
        var html = '<div class="chat-images">';
        for (var j = 0; j < images.length; j++) {
            var img = images[j];
            var src = '';
            if (img.data) {
                var mimeType = img.media_type || img.type || 'image/png';
                src = 'data:' + mimeType + ';base64,' + img.data;
            } else if (img.url) {
                src = img.url;
            }
            if (src) {
                html += '<img class="chat-image-thumb" src="' + src + '" alt="attachment" />';
            }
        }
        html += '</div>';
        return html;
    };

    UIManager.prototype._renderConversationHistory = function(messageHistory) {
        var self = this;
        var html = '<div class="conversation-history">';

        for (var i = 0; i < messageHistory.length; i++) {
            var msg = messageHistory[i];
            var role = msg.role || 'unknown';
            var content = msg.content || '';
            if (!content && !(msg.images && msg.images.length > 0)) continue;

            var renderedContent = content ? self.renderMarkdownSafely(content) : '';
            var isAssistant = role === 'assistant';
            var roleClass = isAssistant ? 'msg-assistant' : 'msg-user';
            var roleLabel = isAssistant ? 'AI Assistant' : 'You';
            var avatarClass = isAssistant ? 'ai' : 'user';
            var avatarText = isAssistant ? 'Ai' : 'You';

            html += '<div class="chat-message ' + roleClass + '">';
            html += '<div class="chat-avatar ' + avatarClass + '">' + avatarText + '</div>';
            html += '<div class="chat-body">';
            html += '<div class="chat-role">' + roleLabel + '</div>';
            html += '<div class="chat-content">' + renderedContent;

            if (msg.images && msg.images.length > 0) {
                html += self._renderChatImages(msg.images);
            }

            html += '</div></div></div>';
        }

        html += '</div>';

        var summaryContent = Utils.safeQuerySelector('#summaryContent');
        if (summaryContent) {
            summaryContent.innerHTML = html;
            this.enhanceChatContent(summaryContent);
            summaryContent.scrollTop = summaryContent.scrollHeight;
        }

        var combinedSummaryContent = Utils.safeQuerySelector('#combinedSummaryContent');
        if (combinedSummaryContent) {
            combinedSummaryContent.innerHTML = html;
            this.enhanceChatContent(combinedSummaryContent);
            combinedSummaryContent.scrollTop = combinedSummaryContent.scrollHeight;
        }
    };

    UIManager.prototype.resetFeedbackForm = function(clearText) {
        var feedbackInput = Utils.safeQuerySelector('#combinedFeedbackText');
        if (feedbackInput) {
            if (clearText === true) {
                feedbackInput.value = '';
            }
            var canInput = this.feedbackState === Utils.CONSTANTS.FEEDBACK_WAITING;
            feedbackInput.disabled = !canInput;
        }

        var submitButtons = [
            Utils.safeQuerySelector('#submitBtn')
        ].filter(function(btn) { return btn !== null; });

        submitButtons.forEach(function(button) {
            button.disabled = false;
            var defaultText = window.i18nManager ? window.i18nManager.t('buttons.submit') : '提交反馈';
            button.textContent = button.getAttribute('data-original-text') || defaultText;
        });
    };

    UIManager.prototype.applyLayoutMode = function(layoutMode) {
        this.layoutMode = layoutMode;
        // In the new three-column design, layout mode only affects internal arrangement
        this.updateTabVisibility();

        if (this.currentTab !== 'combined') {
            this.currentTab = 'combined';
        }

        if (this.onLayoutModeChange) {
            this.onLayoutModeChange(layoutMode);
        }
    };

    UIManager.prototype.getCurrentTab = function() {
        return this.currentTab;
    };

    UIManager.prototype.getFeedbackState = function() {
        return this.feedbackState;
    };

    UIManager.prototype.setLastSubmissionTime = function(timestamp) {
        this.lastSubmissionTime = timestamp;
        this.updateStatusIndicator();
    };

    /**
     * Post-render: wrap code blocks with toolbar and enable lightbox
     */
    UIManager.prototype.enhanceChatContent = function(container) {
        if (!container) return;
        this._enhanceCodeBlocks(container);
        this._enableImageLightbox(container);
    };

    UIManager.prototype._enhanceCodeBlocks = function(container) {
        var pres = container.querySelectorAll('pre');
        for (var i = 0; i < pres.length; i++) {
            var pre = pres[i];
            if (pre.parentElement && pre.parentElement.classList.contains('code-block-wrapper')) continue;

            var codeEl = pre.querySelector('code');
            var lang = '';
            if (codeEl && codeEl.className) {
                var match = codeEl.className.match(/language-(\S+)/);
                if (match) lang = match[1];
            }

            var wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';

            var toolbar = document.createElement('div');
            toolbar.className = 'code-block-toolbar';
            toolbar.innerHTML =
                '<span class="code-block-lang">' + (lang || 'code') + '</span>' +
                '<span class="code-block-actions">' +
                '<button class="code-block-btn btn-copy" title="复制">\u2398</button>' +
                '<span class="fold-indicator">\u25BC</span>' +
                '</span>';

            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(toolbar);
            wrapper.appendChild(pre);

            (function(w, p, tb) {
                var copyBtn = w.querySelector('.btn-copy');

                tb.addEventListener('click', function(e) {
                    if (e.target === copyBtn || copyBtn.contains(e.target)) return;
                    w.classList.toggle('collapsed');
                });

                copyBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var text = p.textContent || p.innerText;
                    var originalHtml = copyBtn.innerHTML;
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text).then(function() {
                            copyBtn.innerHTML = '\u2714';
                            copyBtn.classList.add('copied');
                            setTimeout(function() {
                                copyBtn.innerHTML = originalHtml;
                                copyBtn.classList.remove('copied');
                            }, 2000);
                        });
                    } else {
                        var ta = document.createElement('textarea');
                        ta.value = text;
                        ta.style.position = 'fixed';
                        ta.style.opacity = '0';
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                        copyBtn.innerHTML = '\u2714';
                        copyBtn.classList.add('copied');
                        setTimeout(function() {
                            copyBtn.innerHTML = originalHtml;
                            copyBtn.classList.remove('copied');
                        }, 2000);
                    }
                });
            })(wrapper, pre, toolbar);
        }
    };

    UIManager.prototype._enableImageLightbox = function(container) {
        var imgs = container.querySelectorAll('.chat-image-thumb');
        for (var i = 0; i < imgs.length; i++) {
            if (imgs[i].dataset.lightboxBound) continue;
            imgs[i].dataset.lightboxBound = '1';
            imgs[i].addEventListener('click', function() {
                var overlay = document.createElement('div');
                overlay.className = 'lightbox-overlay';
                var bigImg = document.createElement('img');
                bigImg.src = this.src;
                overlay.appendChild(bigImg);
                document.body.appendChild(overlay);
                overlay.addEventListener('click', function() {
                    overlay.remove();
                });
                document.addEventListener('keydown', function handler(e) {
                    if (e.key === 'Escape') {
                        overlay.remove();
                        document.removeEventListener('keydown', handler);
                    }
                });
            });
        }
    };

    window.MCPFeedback.UIManager = UIManager;
    console.log('UIManager module loaded');
})();
