// Live IST clock for the dashboard card (the topbar date is handled in base_student.html)
function updateDashClock() {
    const now = new Date();
    const time = now.toLocaleTimeString('en-US', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }).toLowerCase();
    const date = now.toLocaleDateString('en-GB', { timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    document.getElementById('liveTime').textContent = time;
    document.getElementById('liveDate').textContent = date;
}
setInterval(updateDashClock, 1000);
updateDashClock();

async function postAttendance(url, btnId, busyHtml, idleHtml, onSuccess) {
    const btn = document.getElementById(btnId);
    btn.disabled = true;
    btn.innerHTML = busyHtml;
    try {
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        if (data.success) onSuccess(data);
        else alert(data.message || 'Request failed.');
    } catch (e) {
        alert('Server error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.innerHTML = idleHtml;
    }
}

function handleClockIn() {
    postAttendance('/api/clock_in', 'btnClockIn',
        '<i class="fa-solid fa-spinner fa-spin"></i> Processing...',
        '<i class="fa-solid fa-play"></i> Clock In', data => {
            document.getElementById('uiClockIn').textContent = data.time;
            document.getElementById('uiClockOut').textContent = '--:--:--';
            document.getElementById('uiDuration').textContent = '00:00:00';
            const s = document.getElementById('attendanceStatus');
            s.textContent = 'In Progress';
            s.className = 'stat-value text-blue';
            document.getElementById('attendanceSub').textContent = `Started at ${data.time}`;
            const m = document.getElementById('trackingMessage');
            m.textContent = 'You are currently clocked in.';
            m.style.color = '#3B82F6';
        });
}

function handleClockOut() {
    postAttendance('/api/clock_out', 'btnClockOut',
        '<i class="fa-solid fa-spinner fa-spin"></i> Processing...',
        '<i class="fa-solid fa-stop"></i> Clock Out', data => {
            document.getElementById('uiClockOut').textContent = data.time;
            document.getElementById('uiDuration').textContent = data.duration;
            const s = document.getElementById('attendanceStatus');
            s.textContent = 'Completed';
            s.className = 'stat-value text-green';
            document.getElementById('attendanceSub').textContent = `Worked ${data.duration}`;
            const m = document.getElementById('trackingMessage');
            m.textContent = `Clock-out recorded at ${data.time}.`;
            m.style.color = '#64748B';
        });
}
