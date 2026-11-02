const tableBody = document.getElementById('taskTableBody');
const emptyState = document.getElementById('emptyState');
const addTaskBtn = document.getElementById('addTaskBtn');
const modal = document.getElementById('taskModal');
const modalTitle = document.getElementById('modalTitle');
const modalClose = document.getElementById('modalClose');
const cancelBtn = document.getElementById('cancelBtn');
const taskForm = document.getElementById('taskForm');

const fId = document.getElementById('taskId');
const fTitle = document.getElementById('taskTitle');
const fAssignee = document.getElementById('taskAssignee');
const fStart = document.getElementById('taskStart');
const fDue = document.getElementById('taskDue');

let tasksData = [];

function escapeHTML(str) { 
    return String(str ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); 
}
function statusClass(s) { 
    return 'status-badge status-' + String(s || 'pending').replace(/_/g, '-'); 
}
function statusLabel(s) {
    if (s === 'pending_approval') return 'Waiting for Approval';
    return String(s).replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

async function fetchStudents() {
    try {
        const res = await fetch('/api/students');
        const students = await res.json();
        if (!res.ok) throw new Error(students.message || 'Could not load students.');

        students.forEach(student => {
            const option = document.createElement('option');
            option.value = student.name;
            option.textContent = student.name;
            fAssignee.appendChild(option);
        });
    } catch (err) {
        console.error('Error fetching students:', err);
        fAssignee.options[0].textContent = 'Could not load students';
    }
}

// Fetch tasks from Database
async function fetchTasks() {
    try {
        const res = await fetch('/api/tasks');
        tasksData = await res.json();
        renderTasks();
    } catch (err) {
        console.error("Error fetching tasks:", err);
    }
}

function renderTasks() {
    tableBody.innerHTML = '';
    const select = document.getElementById('timerTaskSelect');
    select.innerHTML = '<option value="">Select task to track...</option>';

    if (!tasksData || !tasksData.length) { 
        emptyState.classList.add('show'); 
        return; 
    }
    emptyState.classList.remove('show');
    
    tasksData.forEach(t => {
        // Populate timer dropdown, but ONLY for tasks that are pending or in_progress
        if (t.status === 'pending' || t.status === 'in_progress') {
            select.innerHTML += `<option value="${t.id}">${escapeHTML(t.code)} - ${escapeHTML(t.title)}</option>`;
        }

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHTML(t.code)}</td>
            <td>${escapeHTML(t.title)}</td>
            <td>${escapeHTML(t.completedOn || '—')}</td>
            <td>${escapeHTML(t.start || '—')}</td>
            <td>${escapeHTML(t.due || '—')}</td>
            <td>${t.estimate ? escapeHTML(t.estimate) + ' h' : '—'}</td>
            <td>${(Number(t.hoursLogged) || 0).toFixed(2)}</td>
            <td>${escapeHTML(t.assignee || '—')}</td>
            <td><span class="${statusClass(t.status)}">${statusLabel(t.status)}</span></td>
        `;
        // Click row to edit
        tr.style.cursor = 'pointer';
        tr.addEventListener('click', () => openModal(t));
        tableBody.appendChild(tr);
    });
}

function openModal(editTask) {
    modal.classList.remove('hidden'); 
    taskForm.reset(); 
    fId.value = '';
    
    if (editTask) {
        modalTitle.textContent = 'Edit Task'; 
        fId.value = editTask.id; 
        fTitle.value = editTask.title; 
        fAssignee.value = editTask.assignee; 
        if (editTask.assignee && fAssignee.value !== editTask.assignee) {
            const option = document.createElement('option');
            option.value = editTask.assignee;
            option.textContent = `${editTask.assignee} (current)`;
            fAssignee.appendChild(option);
            fAssignee.value = editTask.assignee;
        }
        fStart.value = editTask.start; 
        fDue.value = editTask.due; 
    } else { 
        modalTitle.textContent = 'Add Task'; 
        fStart.value = new Date().toISOString().split('T')[0];
    }
    fTitle.focus();
}

function closeModal() { modal.classList.add('hidden'); }

addTaskBtn.addEventListener('click', () => openModal(null));
modalClose.addEventListener('click', closeModal);
cancelBtn.addEventListener('click', closeModal);
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

taskForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const editingId = fId.value;
    const data = { 
        title: fTitle.value.trim(), 
        assignee: fAssignee.value.trim(), 
        due: fDue.value
    };
    
    if (!data.title) { fTitle.focus(); return; }

    try {
        const url = editingId ? `/api/tasks/${editingId}` : '/api/tasks';
        const method = editingId ? 'PUT' : 'POST';
        
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await res.json();
        if (!res.ok || !result.success) throw new Error(result.message);
        
        closeModal(); 
        fetchTasks(); // Refresh from DB
    } catch (err) {
        alert(err.message || "Failed to save task.");
    }
});

// INITIAL LOAD
fetchStudents();
fetchTasks();


/* TIMER LOGIC (Logs to DB) */
(function headerTimer() {
    const playBtn = document.getElementById('playBtn');
    const timerButtons = document.getElementById('timerButtons');
    const displayEl = document.getElementById('timerDisplay');
    const taskSelect = document.getElementById('timerTaskSelect');

    let elapsedSec = 0;
    let running = false;
    let tickHandle = null;

    function fmt(sec) {
        const h = String(Math.floor(sec / 3600)).padStart(2, '0');
        const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        return `${h}:${m}:${s}`;
    }

    function render() {
        if (running || elapsedSec > 0) {
            displayEl.classList.add('active');
            displayEl.textContent = fmt(elapsedSec);
        } else {
            displayEl.classList.remove('active');
        }

        if (running) {
            timerButtons.innerHTML = `
                <button id="pauseBtn" class="icon-btn" title="Pause"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg></button>
                <button id="stopBtn" class="icon-btn" title="Stop & Submit"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="1"/></svg></button>
            `;
            document.getElementById('pauseBtn').addEventListener('click', pauseTimer);
            document.getElementById('stopBtn').addEventListener('click', stopTimer);
            taskSelect.disabled = true;
        } else if (elapsedSec > 0) {
            timerButtons.innerHTML = `
                <button id="resumeBtn" class="icon-btn" title="Resume" style="background:#eaf2ff; color:#2f6feb; border-color:#2f6feb;"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></button>
                <button id="stopBtn" class="icon-btn" title="Stop & Submit"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="1"/></svg></button>
            `;
            document.getElementById('resumeBtn').addEventListener('click', startTimer);
            document.getElementById('stopBtn').addEventListener('click', stopTimer);
            taskSelect.disabled = true;
        } else {
            timerButtons.innerHTML = `
                <button id="playBtn" class="icon-btn" title="Start" style="background:#eaf2ff; color:#2f6feb; border-color:#2f6feb;"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></button>
            `;
            document.getElementById('playBtn').addEventListener('click', startTimer);
            taskSelect.disabled = false;
        }
    }

    function startTimer() {
        if (!taskSelect.value) {
            alert("Please select a task to track time for first.");
            return;
        }
        running = true;
        render();
        tickHandle = setInterval(() => { elapsedSec++; render(); }, 1000);
    }

    function pauseTimer() {
        running = false;
        clearInterval(tickHandle);
        render();
    }

    async function stopTimer() {
        if (!confirm("Stop timer and submit this time for Admin approval?")) return;
        
        running = false;
        clearInterval(tickHandle);
        
        const hours = elapsedSec / 3600;
        const currentTaskId = taskSelect.value;
        
        // FIX: Removed the 'hours > 0.01' check so it saves even if it's just a few seconds.
        if (elapsedSec > 0) { 
            try {
                const res = await fetch(`/api/tasks/${currentTaskId}/log_time`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hours: hours })
                });
                
                const data = await res.json();
                if (!res.ok || !data.success) throw new Error(data.message);

                // Immediately refresh the table so the UI updates
                fetchTasks(); 
            } catch (err) {
                alert("Failed to log time to database: " + err.message);
            }
        }
        
        // Reset timer UI
        elapsedSec = 0;
        taskSelect.value = '';
        render();
    }

    render();
})();