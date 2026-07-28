(function () {
    const tableStates = new WeakMap();
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

    function getHeaders(table) {
        const thead = table.tHead;
        return thead ? Array.from(thead.querySelectorAll('th')) : [];
    }

    function getState(table) {
        if (!tableStates.has(table)) {
            tableStates.set(table, { columnIndex: null, direction: 'asc' });
        }
        return tableStates.get(table);
    }

    function parseValue(rawValue, type) {
        const value = rawValue == null ? '' : String(rawValue).trim();
        if (!value || value === '-') {
            return null;
        }

        if (type === 'number') {
            const numericValue = Number(value.replace(/,/g, ''));
            return Number.isNaN(numericValue) ? value.toLowerCase() : numericValue;
        }

        if (type === 'date') {
            const timestamp = Date.parse(value);
            return Number.isNaN(timestamp) ? value.toLowerCase() : timestamp;
        }

        if (type === 'boolean') {
            const normalized = value.toLowerCase();
            if (['true', 'yes', '1', 'active', 'admin'].includes(normalized)) {
                return 1;
            }
            if (['false', 'no', '0', 'inactive', 'revoked', 'user'].includes(normalized)) {
                return 0;
            }
            return normalized;
        }

        return value.toLowerCase();
    }

    function compareValues(left, right, direction) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return 1;
        }
        if (right == null) {
            return -1;
        }

        let result = 0;
        if (typeof left === 'number' && typeof right === 'number') {
            result = left - right;
        } else {
            result = collator.compare(String(left), String(right));
        }

        return direction === 'desc' ? -result : result;
    }

    function updateHeaders(table) {
        const state = getState(table);
        const headers = getHeaders(table);

        headers.forEach((header, index) => {
            if (header.dataset.sortable === 'false') {
                header.removeAttribute('aria-sort');
                delete header.dataset.sortDirection;
                return;
            }

            const button = header.querySelector('.adapt-sort-button');
            const indicator = header.querySelector('.adapt-sort-indicator');
            const isActive = state.columnIndex === index;
            const direction = isActive ? state.direction : null;

            header.setAttribute(
                'aria-sort',
                direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'
            );
            if (direction) {
                header.dataset.sortDirection = direction;
            } else {
                delete header.dataset.sortDirection;
            }

            if (button) {
                button.setAttribute(
                    'aria-label',
                    direction === 'asc'
                        ? 'Sort descending'
                        : direction === 'desc'
                            ? 'Clear sort'
                            : 'Sort ascending'
                );
            }
            if (indicator) {
                indicator.textContent = direction === 'asc' ? '^' : direction === 'desc' ? 'v' : '<>';
            }
        });
    }

    function sortTable(table, columnIndex, direction) {
        const tbody = table.tBodies[0];
        if (!tbody) {
            return;
        }

        const headers = getHeaders(table);
        const header = headers[columnIndex];
        if (!header || header.dataset.sortable === 'false') {
            return;
        }

        const type = header.dataset.sortType || 'string';
        const rows = Array.from(tbody.rows).map((row, originalIndex) => ({ row, originalIndex }));

        rows.sort((left, right) => {
            const leftCell = left.row.cells[columnIndex];
            const rightCell = right.row.cells[columnIndex];
            const leftValue = parseValue(
                leftCell && Object.prototype.hasOwnProperty.call(leftCell.dataset, 'sortValue')
                    ? leftCell.dataset.sortValue
                    : leftCell ? leftCell.textContent : '',
                type
            );
            const rightValue = parseValue(
                rightCell && Object.prototype.hasOwnProperty.call(rightCell.dataset, 'sortValue')
                    ? rightCell.dataset.sortValue
                    : rightCell ? rightCell.textContent : '',
                type
            );
            const comparison = compareValues(leftValue, rightValue, direction);
            return comparison !== 0 ? comparison : left.originalIndex - right.originalIndex;
        });

        rows.forEach(({ row }) => tbody.appendChild(row));
        const state = getState(table);
        state.columnIndex = columnIndex;
        state.direction = direction;
        updateHeaders(table);
    }

    function attachHeader(table, header, columnIndex) {
        if (header.dataset.sortable === 'false' || header.querySelector('.adapt-sort-button')) {
            return;
        }

        const label = header.textContent.trim();
        header.textContent = '';

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'adapt-sort-button';

        const labelSpan = document.createElement('span');
        labelSpan.className = 'adapt-sort-label';
        labelSpan.textContent = label;

        const indicator = document.createElement('span');
        indicator.className = 'adapt-sort-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        indicator.textContent = '<>';

        button.appendChild(labelSpan);
        button.appendChild(indicator);
        button.addEventListener('click', () => {
            const state = getState(table);
            const nextDirection =
                state.columnIndex === columnIndex && state.direction === 'asc' ? 'desc' : 'asc';
            sortTable(table, columnIndex, nextDirection);
        });

        header.appendChild(button);
    }

    function initTable(table) {
        if (!table || !table.matches('table[data-sortable-table]')) {
            return;
        }

        getHeaders(table).forEach((header, index) => attachHeader(table, header, index));
        updateHeaders(table);
    }

    function init(root) {
        const target = root || document;
        if (target instanceof HTMLTableElement) {
            initTable(target);
            return;
        }

        target.querySelectorAll('table[data-sortable-table]').forEach(initTable);
    }

    function refresh(root) {
        const target = root || document;
        if (target instanceof HTMLTableElement) {
            const state = getState(target);
            if (state.columnIndex !== null) {
                sortTable(target, state.columnIndex, state.direction);
            } else {
                initTable(target);
            }
            return;
        }

        target.querySelectorAll('table[data-sortable-table]').forEach((table) => refresh(table));
    }

    window.AdaptSortableTables = {
        init,
        refresh,
        sort: sortTable,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => init(document));
    } else {
        init(document);
    }
})();
