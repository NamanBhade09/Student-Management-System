// Clock In / Clock Out toggle for the student dashboard.
//
// The single #btnAttendance button is rendered server-side in three states:
//   - Not started  -> btn-primary,   no .btn-clock-out class  -> click = Clock In
//   - In progress  -> btn-clock-out, .btn-clock-out class     -> click = Clock Out
//   - Completed    -> disabled                                 -> click does nothing
//
// On success we reload the page so the server-rendered times, status badge,
// "tracking message", and the header elapsed timer all stay in sync.
// On failure we surface the message and leave the button enabled so the user
// can retry (previously the page reloaded unconditionally, which was wrong).

async function postAttendance(url) {
    const btn = document.getElementById('btnAttendance');
    if (btn) btn.disabled = true;

    try {
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();

        if (!data.success) {
            alert(data.message || 'Something went wrong.');
            if (btn) btn.disabled = false;
            return;
        }

        window.location.reload();
    } catch (err) {
        console.error(err);
        alert('Network error. Please try again.');
        if (btn) btn.disabled = false;
    }
}

function handleClockIn()  { return postAttendance('/api/clock_in'); }
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

function handleAttendanceToggle() {
    const btn = document.getElementById('btnAttendance');
    if (!btn || btn.disabled) return;
    
    // Check for the exact class name used in your HTML
    if (btn.classList.contains('btn-out')) {
        globalClockOut();
    } else {
        globalClockIn();
    }
}

function handleAttendanceToggle() {
    const btn = document.getElementById('btnAttendance');
    if (!btn || btn.disabled) return;
    
    // If the button is red (Clock Out), trigger Clock Out
    if (btn.classList.contains('btn-out')) {
        globalClockOut();
    } else {
        globalClockIn();
    }
}