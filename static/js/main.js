/**
 * Save-Restricted-Bot Web UI - Main JavaScript
 * Common interactions and utilities
 */

// Toggle search panel
function toggleSearchPanel() {
    const panel = document.getElementById('searchPanel');
    const toggle = document.getElementById('searchToggle');
    if (!panel || !toggle) return;
    
    const isActive = panel.classList.toggle('active');
    toggle.classList.toggle('active', isActive);
}

// Toggle menu dropdown
function toggleMenu() {
    const menu = document.getElementById('menuDropdown');
    if (!menu) return;
    menu.classList.toggle('active');
}

// Close menu and search panel when clicking outside
document.addEventListener('click', function(event) {
    const menu = document.getElementById('menuDropdown');
    const menuToggle = document.querySelector('.menu-toggle');
    const searchPanel = document.getElementById('searchPanel');
    const searchToggle = document.getElementById('searchToggle');
    
    // Close menu if clicking outside
    if (menu && menuToggle && !menuToggle.contains(event.target) && !menu.contains(event.target)) {
        menu.classList.remove('active');
    }
    
    // Close search panel if clicking outside and no filters are active
    if (searchPanel && searchToggle && searchPanel.classList.contains('active')) {
        // Check if we're on notes page and if there are active filters
        const hasFilters = searchPanel.hasAttribute('data-has-filters');
        if (!hasFilters && !searchToggle.contains(event.target) && !searchPanel.contains(event.target)) {
            searchPanel.classList.remove('active');
            searchToggle.classList.remove('active');
        }
    }
});

// Add keyboard shortcuts
document.addEventListener('keydown', function(event) {
    // ESC key closes modals
    if (event.key === 'Escape') {
        closeImageModal();
        closeSelectionModal();
        
        // Close menu
        const menu = document.getElementById('menuDropdown');
        if (menu) menu.classList.remove('active');
    }
    
    // Ctrl/Cmd + K to toggle search (like many modern apps)
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        toggleSearchPanel();
    }
});

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', function() {
    // Sync search toggle state with panel
    const panel = document.getElementById('searchPanel');
    const toggle = document.getElementById('searchToggle');
    if (panel && toggle && panel.classList.contains('active')) {
        toggle.classList.add('active');
    }
});

// Toggle favorite
function toggleFavorite(noteId, btn) {
    fetch(`/toggle_favorite/${noteId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            btn.textContent = btn.textContent === '★' ? '☆' : '★';
        } else {
            alert('操作失败: ' + (data.error || '未知错误'));
        }
    })
    .catch(error => {
        alert('操作失败: ' + error);
    });
}

// Delete note
function deleteNote(noteId) {
    if (!confirm('确定要删除这条笔记吗？此操作不可撤销。')) {
        return;
    }
    
    const card = document.querySelector(`button[onclick="deleteNote(${noteId})"]`).closest('.note-card');
    
    fetch(`/delete_note/${noteId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            card.remove();
        } else {
            alert('删除失败: ' + (data.error || '未知错误'));
        }
    })
    .catch(error => {
        alert('删除失败: ' + error);
    });
}

// Toggle text expand/collapse
function toggleText(noteId) {
    const textDiv = document.getElementById('text-' + noteId);
    const btn = document.getElementById('btn-' + noteId);
    
    if (!textDiv || !btn) return;
    
    if (textDiv.classList.contains('collapsed')) {
        textDiv.classList.remove('collapsed');
        textDiv.classList.add('expanded');
        btn.textContent = '收起';
    } else {
        textDiv.classList.remove('expanded');
        textDiv.classList.add('collapsed');
        btn.textContent = '展开';
    }
}

// Image modal functions
function openImageModal(imageSrc) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('modalImage');
    
    if (!modal || !modalImg) return;
    
    modal.classList.add('active');
    modalImg.src = imageSrc;
    document.body.style.overflow = 'hidden';
}

function closeImageModal() {
    const modal = document.getElementById('imageModal');
    if (!modal) return;
    
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
}

// Selection modal functions
function closeSelectionModal() {
    const modal = document.getElementById('selectionModal');
    if (!modal) return;
    
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
}

function showWatchOptions(noteId, allDns, viewerUrl) {
    const modal = document.getElementById('selectionModal');
    const title = document.getElementById('selectionModalTitle');
    const optionsContainer = document.getElementById('selectionModalOptions');
    
    if (!modal || !title || !optionsContainer) return;
    
    title.textContent = '选择要观看的内容';
    optionsContainer.innerHTML = '';
    
    if (!viewerUrl) {
        alert('未配置观看网站URL，请在管理设置中配置');
        return;
    }
    
    allDns.forEach((dnInfo, index) => {
        if (!dnInfo.dn) return;
        
        const option = document.createElement('div');
        option.className = 'selection-option';
        option.innerHTML = `
            <span class="selection-option-icon">▶️</span>
            <span class="selection-option-text">${dnInfo.dn}</span>
        `;
        option.onclick = function() {
            const watchUrl = viewerUrl + dnInfo.dn;
            console.log('Opening watch URL:', watchUrl);
            window.open(watchUrl, '_blank', 'noopener,noreferrer');
            closeSelectionModal();
        };
        optionsContainer.appendChild(option);
    });
    
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

// Calibrate note
function calibrateNote(noteId, count) {
    const btn = document.getElementById('calibrate-' + noteId);
    if (!btn) return;
    
    const confirmMsg = count > 1
        ? `校准将向机器人发送 ${count} 个磁力链接并获取文件名，\n此操作需要约 ${count * 10} 秒时间。\n\n确定要继续吗？`
        : '校准将向机器人发送磁力链接并获取文件名，\n此操作需要约10秒时间。\n\n确定要继续吗？';
    
    if (!confirm(confirmMsg)) {
        return;
    }
    
    btn.disabled = true;
    btn.textContent = '校准中...';
    
    fetch(`/api/calibrate/${noteId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            btn.textContent = '✓ 已校准';
            
            let resultMsg = `校准完成！\n\n总共: ${data.total}\n成功: ${data.success_count}\n失败: ${data.fail_count}`;
            
            if (data.results && data.results.length > 0) {
                resultMsg += '\n\n详细结果:\n';
                data.results.forEach((result, index) => {
                    if (result.success) {
                        resultMsg += `${index + 1}. ✓ ${result.filename || '(空文件名)'}\n`;
                    } else {
                        resultMsg += `${index + 1}. ✗ ${result.error}\n`;
                    }
                });
            }
            
            alert(resultMsg);
            saveScrollPosition();
            setTimeout(() => location.reload(), 1000);
        } else {
            alert('校准失败: ' + (data.error || '未知错误'));
            btn.disabled = false;
            btn.textContent = count > 1 ? `校准(${count})` : '校准';
        }
    })
    .catch(error => {
        alert('校准失败: ' + error);
        btn.disabled = false;
        btn.textContent = count > 1 ? `校准(${count})` : '校准';
    });
}

// Scroll position management
function saveScrollPosition() {
    sessionStorage.setItem('scrollPosition', window.pageYOffset || document.documentElement.scrollTop);
}

function restoreScrollPosition() {
    const scrollPosition = sessionStorage.getItem('scrollPosition');
    if (scrollPosition) {
        window.scrollTo(0, parseInt(scrollPosition));
        sessionStorage.removeItem('scrollPosition');
    }
}

// Initialize page-specific features
document.addEventListener('DOMContentLoaded', function() {
    // Restore scroll position
    restoreScrollPosition();
    
    // Check which text blocks need expand buttons
    const noteTexts = document.querySelectorAll('.note-text');
    noteTexts.forEach(function(textDiv) {
        const scrollHeight = textDiv.scrollHeight;
        const clientHeight = 150;
        
        if (scrollHeight > clientHeight) {
            const noteId = textDiv.id.replace('text-', '');
            const btn = document.getElementById('btn-' + noteId);
            if (btn) {
                btn.style.display = 'inline-block';
            }
        }
    });
    
    // Add click handlers to all images for modal view
    const allImages = document.querySelectorAll('.note-media-item img, .note-image');
    allImages.forEach(function(img) {
        img.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            openImageModal(this.src);
        });
    });
    
    // Add event listeners for multi-watch buttons
    const watchButtons = document.querySelectorAll('.btn-watch-multi');
    watchButtons.forEach(function(btn) {
        btn.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            
            const noteId = this.getAttribute('data-note-id');
            const dnsJson = this.getAttribute('data-dns');
            const viewerUrl = this.getAttribute('data-viewer-url');
            
            try {
                const allDns = JSON.parse(dnsJson);
                showWatchOptions(noteId, allDns, viewerUrl);
            } catch (e) {
                console.error('解析 DNS 数据失败:', e);
                alert('数据解析失败: ' + e.message);
            }
        });
    });
});
