/**
 * Sidebar Navigation Component
 * Iniettato dinamicamente in ogni pagina
 */
(function() {
    'use strict';

    // Rilevamento iframe: non iniettare sidebar se siamo dentro un iframe
    if (window !== window.parent) return;

    // Carica CSS sidebar se non presente
    if (!document.querySelector('link[href*="sidebar.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/sidebar.css';
        document.head.appendChild(link);
    }

    const currentPath = window.location.pathname;

    const navGroups = [
        {
            label: 'Main',
            items: [
                { icon: 'fas fa-home', label: 'Home', path: '/', tooltip: 'Home' },
                { icon: 'fas fa-users-cog', label: 'Investigate', path: '/investigation', tooltip: 'Investigate' },
                { icon: 'fas fa-user-friends', label: 'People', path: '/people', tooltip: 'People' },
                { icon: 'fas fa-brain', label: 'Archive', path: '/archive', tooltip: 'Archive' },
                { icon: 'fas fa-map-marked-alt', label: 'Map', path: '/map', tooltip: 'Map' }
            ]
        },
        {
            label: 'Tools',
            collapsible: true,
            items: [
                { icon: 'fas fa-code-merge', label: 'Merge', path: '/merge', tooltip: 'Merge' },
                { icon: 'fas fa-layer-group', label: 'Synthesis', path: '/sintesi', tooltip: 'Synthesis' },
                { icon: 'fas fa-images', label: 'Gallery', path: '/gallery', tooltip: 'Gallery' },
                { icon: 'fas fa-plane', label: 'Flights', path: '/flights', tooltip: 'Flights' }
            ]
        }
    ];

    // Build sidebar HTML
    let navHTML = '';
    navGroups.forEach(group => {
        const isCollapsible = group.collapsible === true;
        const storageKey = 'sidebar-group-' + group.label;
        const savedState = localStorage.getItem(storageKey);
        // Collapsible groups: closed by default unless user opened them
        const isCollapsed = isCollapsible && savedState !== 'open';

        const collapsibleClass = isCollapsible ? ' collapsible' : '';
        const collapsedClass = isCollapsed ? ' collapsed' : '';
        const chevronHTML = isCollapsible ? '<i class="fas fa-chevron-down chevron"></i>' : '';

        navHTML += `<div class="nav-group-label${collapsibleClass}${collapsedClass}" data-group="${group.label}">${group.label}${chevronHTML}</div>`;
        navHTML += `<div class="nav-group-items${collapsedClass}" data-group-items="${group.label}">`;
        group.items.forEach(item => {
            const isActive = currentPath === item.path ? ' active' : '';
            const badge = item.badge ? `<span class="nav-badge ${item.badgeClass || ''}">${item.badge}</span>` : '';
            navHTML += `<a href="${item.path}" class="nav-item${isActive}" data-tooltip="${item.tooltip}">
                <i class="${item.icon}"></i>
                <span class="nav-label">${item.label}</span>
                ${badge}
            </a>`;
        });
        navHTML += '</div>';
    });

    // Settings link in fondo
    navHTML += '<div class="nav-group-separator"></div>';
    navHTML += `<a href="/settings" class="nav-item${currentPath === '/settings' ? ' active' : ''}" data-tooltip="Settings">
        <i class="fas fa-cog"></i>
        <span class="nav-label">Settings</span>
    </a>`;

    const sidebarHTML = `
        <div class="app-sidebar" id="appSidebar">
            <div class="sidebar-header">
                <i class="fas fa-fingerprint sidebar-logo"></i>
                <div class="sidebar-title">Parrhe<span>sepstein</span></div>
                <button class="sidebar-toggle" id="sidebarToggle" title="Collapse/Expand">
                    <i class="fas fa-chevron-left"></i>
                </button>
            </div>
            <nav class="sidebar-nav">
                ${navHTML}
            </nav>
        </div>
        <button class="mobile-hamburger" id="mobileHamburger">
            <i class="fas fa-bars"></i>
        </button>
        <div class="sidebar-overlay" id="sidebarOverlay"></div>
    `;

    function initSidebar() {
        // Se gia' inizializzata, skip
        if (document.getElementById('appSidebar')) return;

        // Inject sidebar all'inizio del body
        document.body.insertAdjacentHTML('afterbegin', sidebarHTML);

        // Wrap tutto il contenuto esistente (esclusa sidebar) in .main-content
        if (!document.querySelector('.main-content')) {
            const children = Array.from(document.body.children).filter(
                el => !el.classList.contains('app-sidebar') &&
                      !el.classList.contains('mobile-hamburger') &&
                      !el.classList.contains('sidebar-overlay') &&
                      el.tagName !== 'SCRIPT' &&
                      el.tagName !== 'LINK' &&
                      el.tagName !== 'STYLE'
            );

            if (children.length > 0) {
                const wrapper = document.createElement('div');
                wrapper.className = 'main-content';
                // Inserisci il wrapper prima del primo figlio non-sidebar
                children[0].parentNode.insertBefore(wrapper, children[0]);
                children.forEach(child => wrapper.appendChild(child));
            }
        }

        // Sidebar toggle
        const sidebar = document.getElementById('appSidebar');
        const toggleBtn = document.getElementById('sidebarToggle');
        const hamburger = document.getElementById('mobileHamburger');
        const overlay = document.getElementById('sidebarOverlay');

        if (!sidebar || !toggleBtn) return;

        // Load saved state (default: collapsed)
        const saved = localStorage.getItem('sidebar-collapsed');
        if (saved !== 'false') {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
            toggleBtn.querySelector('i').classList.replace('fa-chevron-left', 'fa-chevron-right');
        }

        toggleBtn.addEventListener('click', function() {
            sidebar.classList.toggle('collapsed');
            document.body.classList.toggle('sidebar-collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            localStorage.setItem('sidebar-collapsed', isCollapsed);
            const icon = toggleBtn.querySelector('i');
            if (isCollapsed) {
                icon.classList.replace('fa-chevron-left', 'fa-chevron-right');
            } else {
                icon.classList.replace('fa-chevron-right', 'fa-chevron-left');
            }
        });

        // Collapsible group toggle
        document.querySelectorAll('.nav-group-label.collapsible').forEach(label => {
            label.addEventListener('click', function() {
                const groupName = this.dataset.group;
                const items = document.querySelector(`.nav-group-items[data-group-items="${groupName}"]`);
                const isCollapsed = this.classList.toggle('collapsed');
                if (items) {
                    items.classList.toggle('collapsed', isCollapsed);
                }
                // Save state
                localStorage.setItem('sidebar-group-' + groupName, isCollapsed ? 'closed' : 'open');
            });
        });

        // Mobile
        if (hamburger) {
            hamburger.addEventListener('click', function() {
                sidebar.classList.toggle('mobile-open');
                overlay.classList.toggle('active');
            });
        }

        if (overlay) {
            overlay.addEventListener('click', function() {
                sidebar.classList.remove('mobile-open');
                overlay.classList.remove('active');
            });
        }
    }

    // Aspetta che il DOM sia pronto prima di inizializzare
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebar);
    } else {
        // DOM gia' pronto (script caricato tardi o defer)
        initSidebar();
    }

})();
