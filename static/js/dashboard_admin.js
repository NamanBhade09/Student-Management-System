(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pad = n => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const CYCLE = ['', 'Present', 'Absent', 'Late', 'Half-day'];
  const SYMBOL = {Present: ['P','P'], Absent: ['A','A'], Late: ['L','L'], 'Half-day': ['H','H']};
  const now = new Date();
  const todayIso = iso(now.getFullYear(), now.getMonth(), now.getDate());
  let students = [], holidays = {}, holView = new Date(now.getFullYear(), now.getMonth(), 1);
  let msgTimer;

  function say(text, bad) {
    const el = $('adminMessage');
    el.textContent = text;
    el.style.color = bad ? '#d1242f' : '#1f9d4c';
    clearTimeout(msgTimer);
    msgTimer = setTimeout(() => el.textContent = '', 3500);
  }

  async function api(url, method = 'GET', body) {
    try {
      const res = await fetch(url, {
        method, headers: {'Content-Type': 'application/json'},
        body: body ? JSON.stringify(body) : undefined
      });
      if (res.status === 401) { location.href = '/'; return null; }
      const data = await res.json();
      if (!res.ok || data.success === false) throw new Error(data.message || 'Request failed.');
      return data;
    } catch (e) {
      say(e.message || 'Server error.', true);
      return null;
    }
  }

  // ---------- navigation
  const titles = {dashboard: 'Dashboard', leaves: 'Leave approvals', attendance: 'Attendance', tasks: 'Tasks', holidays: 'Holidays', students: 'Students', password: 'Change password'};
  const loaders = {dashboard: loadDashboard, leaves: loadLeaves, attendance: loadAttendance, tasks: loadTasks, holidays: loadHolidays, students: loadStudentsPage, password: () => {}};
  document.querySelectorAll('#nav button').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.page)));
  function show(page) {
    document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === page));
    $('pageTitle').textContent = titles[page];
    loaders[page]();
  }

  // ---------- dashboard
  async function loadDashboard() {
    const s = await api('/api/admin/summary');
    if (s) $('stats').innerHTML = [
      ['Total students', s.students], ['Present today', s.present],
      ['Pending leaves', s.leaves], ['Open tasks', s.tasks]
    ].map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join('');
    const leaves = await api('/api/admin/leaves');
    if (!leaves) return;
    const pending = leaves.filter(l => l.status === 'Pending');
    $('dashLeaves').innerHTML = pending.length
      ? `<table><thead><tr><th>Student</th><th>Type</th><th>Dates</th><th></th></tr></thead><tbody>${pending.map(l =>
          `<tr><td>${esc(l.student)}</td><td>${esc(l.type)}</td><td>${l.start} → ${l.end}</td><td>${actions(l.id)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="legend">No pending leave requests.</p>';
  }

  // ---------- leaves
  const actions = id => `<button class="btn ok sm" data-leave="${id}" data-status="Approved">Approve</button><button class="btn no sm" data-leave="${id}" data-status="Rejected">Reject</button>`;

  async function loadLeaves() {
    const leaves = await api('/api/admin/leaves');
    if (!leaves) return;
    $('leaveBody').innerHTML = leaves.length ? leaves.map(l => `<tr>
      <td>${esc(l.student)}</td><td>${esc(l.type)}</td><td>${l.start}</td><td>${l.end}</td>
      <td>${esc(l.reason)}</td><td><span class="badge ${l.status}">${l.status}</span></td>
      <td>${l.status === 'Pending' ? actions(l.id) : ''}</td></tr>`).join('')
      : '<tr><td colspan="7" class="legend">No leave requests.</td></tr>';
  }

  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-leave]');
    if (!b) return;
    b.disabled = true;
    const r = await api(`/api/admin/leaves/${b.dataset.leave}`, 'POST', {status: b.dataset.status});
    if (r) { say(`Leave ${b.dataset.status.toLowerCase()}.`); loaders[document.querySelector('.page.active').id](); }
    else b.disabled = false;
  });

  // ---------- attendance grid
  async function loadStudents() {
    if (!students.length) students = (await api('/api/admin/students')) || [];
    return students;
  }
  async function loadAttendance() {
    const month = $('attMonth').value || (now.getFullYear() + '-' + pad(now.getMonth() + 1));
    $('attMonth').value = month;
    await loadStudents();
    const d = await api('/api/admin/attendance?month=' + month);
    if (!d) return;
    let h = '<thead><tr><th>Student</th>';
    for (let i = 1; i <= d.days; i++) h += `<th>${i}</th>`;
    h += '</tr></thead><tbody>';
    students.forEach(s => {
      h += `<tr><td>${esc(s.name)}</td>`;
      for (let i = 1; i <= d.days; i++) {
        const st = (d.records[s.id] || {})[i] || '';
        const date = `${month}-${pad(i)}`;
        h += `<td class="cell ${st ? SYMBOL[st][0] : ''}" data-sid="${s.id}" data-date="${date}" data-status="${st}">${st ? SYMBOL[st][1] : '·'}</td>`;
      }
      h += '</tr>';
    });
    $('attTable').innerHTML = h + '</tbody>';
  }
  $('attMonth').addEventListener('change', loadAttendance);
  $('attTable').addEventListener('click', async e => {
    const c = e.target.closest('td.cell');
    if (!c) return;
    const next = CYCLE[(CYCLE.indexOf(c.dataset.status) + 1) % CYCLE.length];
    const r = await api('/api/admin/attendance', 'POST', {student_id: c.dataset.sid, date: c.dataset.date, status: next});
    if (!r) return;
    c.dataset.status = next;
    c.className = 'cell ' + (next ? SYMBOL[next][0] : '');
    c.textContent = next ? SYMBOL[next][1] : '·';
  });

  // ---------- tasks
  async function loadTasks() {
    await loadStudents();
    const sel = $('taskStudent'), keep = sel.value;
    sel.innerHTML = '<option value="">Choose student</option>' + students.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
    sel.value = keep;
    const tasks = await api('/api/admin/tasks');
    if (!tasks) return;
    $('taskBody').innerHTML = tasks.length ? tasks.map(t => {
      const done = t.status === 'completed';
      return `<tr><td>${esc(t.title)}<br><span class="legend">${esc(t.student)}</span></td><td>${t.due}</td>
        <td><span class="badge ${done ? 'Done' : 'Open'}">${done ? 'Done' : t.status === 'in_progress' ? 'In progress' : 'Open'}</span></td>
        <td><button class="btn no sm" data-del="${t.id}">Delete</button></td></tr>`;
    }).join('') : '<tr><td colspan="4" class="legend">No tasks assigned.</td></tr>';
  }
  $('taskForm').addEventListener('submit', async e => {
    e.preventDefault();
    const r = await api('/api/admin/tasks', 'POST', {
      student_id: $('taskStudent').value, title: $('taskTitle').value,
      description: $('taskDescription').value, due_date: $('taskDue').value
    });
    if (r) { say('Task assigned.'); e.target.reset(); loadTasks(); }
  });
  $('taskBody').addEventListener('click', async e => {
    const b = e.target.closest('[data-del]');
    if (!b || !confirm('Delete this task?')) return;
    if (await api(`/api/admin/tasks/${b.dataset.del}/delete`, 'POST')) { say('Task deleted.'); loadTasks(); }
  });

  // ---------- holidays
  async function loadHolidays() {
    holidays = (await api('/api/admin/holidays')) || holidays;
    renderHolidays();
  }
  function renderHolidays() {
    const y = holView.getFullYear(), m = holView.getMonth();
    $('holMonth').textContent = `${MONTHS[m]} ${y}`;
    const lead = (new Date(y, m, 1).getDay() + 6) % 7;
    const dim = new Date(y, m + 1, 0).getDate();
    let h = '';
    for (let i = 0; i < lead; i++) h += '<div class="day other"></div>';
    for (let d = 1; d <= dim; d++) {
      const key = iso(y, m, d);
      h += `<div class="day ${key === todayIso ? 'today' : ''}" data-date="${key}">${d}${holidays[key] ? `<span class="hol">${esc(holidays[key])}</span>` : ''}</div>`;
    }
    $('holGrid').innerHTML = h;
  }
  $('prev').addEventListener('click', () => { holView.setMonth(holView.getMonth() - 1); renderHolidays(); });
  $('next').addEventListener('click', () => { holView.setMonth(holView.getMonth() + 1); renderHolidays(); });
  $('holGrid').addEventListener('click', async e => {
    const c = e.target.closest('.day[data-date]');
    if (!c) return;
    const date = c.dataset.date;
    if (holidays[date]) {
      if (!confirm(`Remove "${holidays[date]}" on ${date}?`)) return;
      if (await api('/api/admin/holidays', 'DELETE', {date})) { delete holidays[date]; say('Holiday removed.'); renderHolidays(); }
    } else {
      const name = prompt(`Holiday name for ${date}:`);
      if (!name || !name.trim()) return;
      if (await api('/api/admin/holidays', 'POST', {date, name: name.trim()})) { holidays[date] = name.trim(); say('Holiday added.'); renderHolidays(); }
    }
  });

  // ---------- students
  let editId = null, stuRows = [];
  async function loadStudentsPage() {
    const rows = await api('/api/admin/student-list');
    if (!rows) return;
    stuRows = rows;
    $('stuBody').innerHTML = rows.length ? rows.map(s => `<tr>
      <td>${esc(s.firstname)} ${esc(s.lastname)}</td><td>${esc(s.username)}</td><td>${esc(s.email)}</td><td>${esc(s.city)}</td>
      <td><button class="btn ghost sm" data-edit="${s.id}">Edit</button><button class="btn no sm" data-rm="${s.id}">Delete</button></td></tr>`).join('')
      : '<tr><td colspan="5" class="legend">No students yet.</td></tr>';
  }
  function resetStuForm() {
    editId = null;
    $('stuForm').reset();
    $('sUser').disabled = false;
    $('sPass').required = true;
    $('sPass').placeholder = 'Password (min 8)';
    $('stuFormTitle').textContent = 'Add student';
    $('stuSubmit').textContent = 'Add student';
    $('stuCancel').hidden = true;
  }
  $('stuCancel').addEventListener('click', resetStuForm);
  $('stuBody').addEventListener('click', async e => {
    const ed = e.target.closest('[data-edit]'), rm = e.target.closest('[data-rm]');
    if (ed) {
      const s = stuRows.find(x => String(x.id) === ed.dataset.edit);
      editId = s.id;
      $('sUser').value = s.username; $('sUser').disabled = true;
      $('sPass').value = ''; $('sPass').required = false; $('sPass').placeholder = 'New password (optional)';
      $('sFirst').value = s.firstname; $('sLast').value = s.lastname; $('sEmail').value = s.email;
      $('sMobile').value = s.mobile_no; $('sGender').value = s.gender; $('sDob').value = s.dob; $('sCity').value = s.city;
      $('stuFormTitle').textContent = 'Edit student';
      $('stuSubmit').textContent = 'Save changes';
      $('stuCancel').hidden = false;
      $('stuForm').scrollIntoView({behavior: 'smooth'});
    } else if (rm) {
      if (!confirm('Delete this student? Their login, tasks, attendance and leave records will also be deleted.')) return;
      if (await api(`/api/admin/student-list/${rm.dataset.rm}`, 'DELETE')) {
        say('Student deleted.'); students = []; if (editId) resetStuForm(); loadStudentsPage();
      }
    }
  });
  $('stuForm').addEventListener('submit', async e => {
    e.preventDefault();
    const body = {
      username: $('sUser').value, password: $('sPass').value, firstname: $('sFirst').value,
      lastname: $('sLast').value, email: $('sEmail').value, mobile_no: $('sMobile').value,
      gender: $('sGender').value, dob: $('sDob').value, city: $('sCity').value
    };
    const r = editId
      ? await api(`/api/admin/student-list/${editId}`, 'PUT', body)
      : await api('/api/admin/student-list', 'POST', body);
    if (r) { say(editId ? 'Student updated.' : 'Student added.'); students = []; resetStuForm(); loadStudentsPage(); }
  });

  // ---------- change password
  $('pwForm').addEventListener('submit', async e => {
    e.preventDefault();
    const r = await api('/api/change_password', 'POST', {
      current_password: $('curPw').value, new_password: $('newPw').value, confirm_password: $('confPw').value
    });
    if (r) { say('Password updated.'); e.target.reset(); }
  });

  // ---------- init
  $('todayLabel').textContent = now.toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  $('attMonth').value = now.getFullYear() + '-' + pad(now.getMonth() + 1);
  loadDashboard();
})();
