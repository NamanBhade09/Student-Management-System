document.addEventListener("DOMContentLoaded", () => {
    // --- 1. Live Clock Logic (IST) ---
    function updateClock() {
        const now = new Date();
        const timeOptions = { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true };
        const timeStr = now.toLocaleTimeString('en-US', timeOptions).toLowerCase();
        const dateOptions = { timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
        const dateStr = now.toLocaleDateString('en-GB', dateOptions);
        
        const liveTimeEl = document.getElementById('liveTime');
        const liveDateEl = document.getElementById('liveDate');
        
        if (liveTimeEl) liveTimeEl.textContent = timeStr;
        if (liveDateEl) liveDateEl.textContent = dateStr;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // --- 2. Clock Toggle Button Logic ---
    const btnClockToggle = document.getElementById('btnClockToggle');
    
    // Read the initial state rendered by Flask
    let currentState = btnClockToggle.getAttribute('data-state');

    // Function to update button text and colors based on state
    function applyButtonState(state) {
        currentState = state;
        btnClockToggle.setAttribute('data-state', state);
        
        if (state === 'in') {
            btnClockToggle.textContent = 'Clock In';
            btnClockToggle.className = 'clock-toggle is-in';
            btnClockToggle.disabled = false;
        } else if (state === 'out') {
            btnClockToggle.textContent = 'Clock Out';
            btnClockToggle.className = 'clock-toggle is-out';
            btnClockToggle.disabled = false;
        } else if (state === 'done') {
            btnClockToggle.textContent = 'Completed';
            btnClockToggle.className = 'clock-toggle is-done';
            btnClockToggle.disabled = true;
        }
    }

    // Initialize button style on page load
    applyButtonState(currentState);

    // Handle button click
    btnClockToggle.addEventListener('click', async () => {
        // Prevent clicking if already done
        if (currentState === 'done') return;

        const originalText = btnClockToggle.textContent;
        btnClockToggle.disabled = true;
        btnClockToggle.textContent = 'Processing...';

        try {
            if (currentState === 'in') {
                // --- Handle Clock In ---
                const response = await fetch('/api/clock_in', { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('uiClockIn').textContent = data.time;
                    document.getElementById('uiClockOut').textContent = "--:--:--";
                    document.getElementById('uiDuration').textContent = "00:00:00";
                    
                    const statusEl = document.getElementById('attendanceStatus');
                    statusEl.textContent = "In Progress";
                    statusEl.className = "stat-value text-blue";
                    document.getElementById('attendanceSub').textContent = `Started at ${data.time}`;
                    
                    const msg = document.getElementById('trackingMessage');
                    msg.textContent = "You are currently clocked in.";
                    msg.style.color = "#3B82F6";
                    
                    // Switch state to 'out'
                    applyButtonState('out');
                } else {
                    alert(data.message || "Could not clock in.");
                    btnClockToggle.textContent = originalText;
                    btnClockToggle.disabled = false;
                }

            } else if (currentState === 'out') {
                // --- Handle Clock Out ---
                const response = await fetch('/api/clock_out', { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('uiClockOut').textContent = data.time;
                    document.getElementById('uiDuration').textContent = data.duration;
                    
                    const statusEl = document.getElementById('attendanceStatus');
                    statusEl.textContent = "Completed";
                    statusEl.className = "stat-value text-green";
                    
                    const msg = document.getElementById('trackingMessage');
                    msg.textContent = `Clock-out recorded for ${data.time}.`;
                    msg.style.color = "#64748B";
                    
                    // Switch state to 'done'
                    applyButtonState('done');
                } else {
                    alert(data.message || "Could not clock out.");
                    btnClockToggle.textContent = originalText;
                    btnClockToggle.disabled = false;
                }
            }
        } catch (error) {
            console.error(error);
            alert("Server error. Please try again.");
            btnClockToggle.textContent = originalText;
            btnClockToggle.disabled = false;
        }
    });
});
// Single button: Clock In when not started, Clock Out while running.
// The page reloads after success so the server-rendered times, status and
// timer in dashboard_student.html all stay in sync.

async function postAttendance(url) {
    const btn = document.getElementById('btnAttendance');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        
        // FIXED: Using data.success to match app.py
        if (!data.success) alert(data.message || 'Something went wrong.');
        window.location.reload();
    } catch (err) {
        alert('Network error. Please try again.');
        if (btn) btn.disabled = false;
    }
}

// FIXED: Using /api/clock_in with underscore
function handleClockIn()  { return postAttendance('/api/clock_in'); }

// FIXED: Using /api/clock_out with underscore
function handleClockOut() { return postAttendance('/api/clock_out'); }

function handleAttendanceToggle() {
    const btn = document.getElementById('btnAttendance');
    if (!btn || btn.disabled) return;
    if (btn.classList.contains('btn-clock-out')) {
        handleClockOut();
    } else {
        handleClockIn();
    }
}