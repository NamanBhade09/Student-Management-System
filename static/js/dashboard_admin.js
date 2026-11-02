(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pad = n => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const SYMBOL = {Present: ['P','P'], Absent: ['A','A'], Late: ['L','L'], 'Half-day': ['H','H']};
  const now = new Date();
  const todayIso = iso(now.getFullYear(), now.getMonth(), now.getDate());
  
  let students = [], holidays = {}, holView = new Date(now.getFullYear(), now.getMonth(), 1), allLeaves = [];
  let editId = null, stuRows = [];
  let attendanceSchedules = new Map();
  let attendanceData = null;
  let activeAttendanceRefresh = null;
  let activeAttendanceRequest = false;

  // --- TOAST NOTIFICATIONS ---
  function showToast(message, type = 'success') {
    const container = $('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? 'fa-circle-check' : 'fa-circle-exclamation';
    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${esc(message)}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
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
      showToast(e.message || 'Server error.', 'error');
      return null;
    }
  }

  // --- NAVIGATION ---
  const titles = {dashboard: 'Dashboard', leaves: 'Leave Approvals', attendance: 'Attendance', tasks: 'Tasks', holidays: 'Holidays', students: 'Students', password: 'Security'};
  const loaders = {dashboard: loadDashboard, leaves: loadLeaves, attendance: loadAttendance, tasks: loadTasks, holidays: loadHolidays, students: loadStudentsPage, password: () => {}};
  
  const sidebar = document.querySelector('.sidebar');
  const menuToggle = $('mobileMenuToggle');
  const closeMobileMenu = () => {
    sidebar?.classList.remove('mobile-nav-open');
    menuToggle?.setAttribute('aria-expanded', 'false');
    menuToggle?.setAttribute('aria-label', 'Open navigation menu');
    if (menuToggle) {
      menuToggle.querySelector('i').className = 'fa-solid fa-bars';
      menuToggle.querySelector('span').textContent = 'Menu';
    }
  };

  menuToggle?.addEventListener('click', () => {
    const isOpen = sidebar.classList.toggle('mobile-nav-open');
    menuToggle.setAttribute('aria-expanded', String(isOpen));
    menuToggle.setAttribute('aria-label', isOpen ? 'Close navigation menu' : 'Open navigation menu');
    menuToggle.querySelector('i').className = `fa-solid ${isOpen ? 'fa-xmark' : 'fa-bars'}`;
    menuToggle.querySelector('span').textContent = isOpen ? 'Close' : 'Menu';
  });
  document.querySelectorAll('#nav button').forEach(btn => btn.addEventListener('click', () => {
    show(btn.dataset.page);
    closeMobileMenu();
  }));
  document.addEventListener('click', event => {
    if (!sidebar?.contains(event.target)) closeMobileMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sidebar?.classList.contains('mobile-nav-open')) {
      closeMobileMenu();
      menuToggle?.focus();
    }
  });
  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) closeMobileMenu();
  });
  
  window.show = function(page) {
    document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === page));
    if($('pageTitle')) $('pageTitle').textContent = titles[page];
    if($('pageBreadcrumb')) $('pageBreadcrumb').textContent = titles[page];
    loaders[page]();
  };

  // --- DASHBOARD ---
  function renderActiveAttendance(activeStudents) {
    $('activeAttendance').innerHTML = activeStudents.length
      ? `<table><thead><tr><th>Student</th><th>Clock In</th><th>Status</th></tr></thead><tbody>${activeStudents.map(student =>
          `<tr><td>${esc(student.name)}</td><td>${esc(student.clockIn)}</td><td><span class="badge Open">Active</span></td></tr>`).join('')}</tbody></table>`
      : '<p class="legend">No students are currently clocked in.</p>';
  }

  async function refreshActiveAttendance() {
    if (activeAttendanceRequest || document.hidden || !$('dashboard').classList.contains('active')) return;
    activeAttendanceRequest = true;
    try {
      const data = await api('/api/admin/active-attendance');
      if (data) renderActiveAttendance(data.activeStudents);
    } finally {
      activeAttendanceRequest = false;
    }
  }

  async function loadDashboard() {
    const s = await api('/api/admin/summary');
    if (s) {
      $('stats').innerHTML = `
        <div class="stat clickable" role="button" tabindex="0" onclick="show('students')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();show('students')}">
          <div class="stat-icon" style="background:#EFF6FF; color:#3B82F6;"><i class="fa-solid fa-users"></i></div>
          <div class="stat-info"><b>${s.students}</b><span>Total Students</span></div>
        </div>
        <div class="stat clickable" onclick="show('attendance')">
          <div class="stat-icon" style="background:#ECFDF5; color:#10B981;"><i class="fa-solid fa-user-check"></i></div>
          <div class="stat-info"><b>${s.present}</b><span>Present Today</span></div>
        </div>
        <div class="stat clickable" onclick="show('leaves')">
          <div class="stat-icon" style="background:#FFF7ED; color:#F59E0B;"><i class="fa-regular fa-calendar-xmark"></i></div>
          <div class="stat-info"><b>${s.leaves}</b><span>Pending Leaves</span></div>
        </div>
        <div class="stat clickable" onclick="show('tasks')">
          <div class="stat-icon" style="background:#FEF2F2; color:#EF4444;"><i class="fa-solid fa-list-check"></i></div>
          <div class="stat-info"><b>${s.tasks}</b><span>Open Tasks</span></div>
        </div>
      `;
      renderActiveAttendance(s.activeStudents);
      if (!activeAttendanceRefresh) {
        activeAttendanceRefresh = setInterval(refreshActiveAttendance, 5000);
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && $('dashboard').classList.contains('active')) {
        refreshActiveAttendance();
      }
    });
    
    const leaves = await api('/api/admin/leaves');
    if (!leaves) return;
    const pending = leaves.filter(l => l.status === 'Pending');
    $('dashLeaves').innerHTML = pending.length
      ? `<table><thead><tr><th>Student</th><th>Type</th><th>Dates</th><th>Action</th></tr></thead><tbody>${pending.map(l =>
          `<tr><td>${esc(l.student)}</td><td>${esc(l.type)}</td><td>${l.start} &rarr; ${l.end}</td><td>${leaveActions(l.id)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="legend">No pending leave requests.</p>';

  }

  // --- LEAVES ---
  const leaveActions = id => `<button class="btn ok sm" data-leave="${id}" data-status="Approved">Approve</button><button class="btn no sm" data-leave="${id}" data-status="Rejected">Reject</button>`;

  async function loadLeaves() {
    allLeaves = await api('/api/admin/leaves');
    if (!allLeaves) return;
    renderLeaves();
  }

  function renderLeaves() {
    const filter = $('leaveFilter').value;
    const filtered = filter === 'All' ? allLeaves : allLeaves.filter(l => l.status === filter);
    
    $('leaveBody').innerHTML = filtered.length ? filtered.map(l => `<tr>
      <td>${esc(l.student)}</td><td>${esc(l.type)}</td><td>${l.start}</td><td>${l.end}</td>
      <td>${esc(l.reason)}</td><td><span class="badge ${l.status}">${l.status}</span></td>
      <td>${l.status === 'Pending' ? leaveActions(l.id) : ''}</td></tr>`).join('')
      : '<tr><td colspan="7" class="legend" style="text-align:center;">No leave requests found.</td></tr>';
  }

  $('leaveFilter')?.addEventListener('change', renderLeaves);

  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-leave]');
    if (!b) return;
    b.disabled = true;
    const r = await api(`/api/admin/leaves/${b.dataset.leave}`, 'POST', {status: b.dataset.status});
    if (r) { 
      showToast(`Leave ${b.dataset.status.toLowerCase()}.`); 
      loaders[document.querySelector('.page.active').id](); 
    } else {
      b.disabled = false;
    }
  });

  // --- ATTENDANCE ---
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
    attendanceData = d;
    attendanceSchedules = new Map(d.schedules.map(schedule => [String(schedule.studentId), schedule]));

    const attendanceStudent = $('attendanceStudent');
    const selectedStudent = attendanceStudent.value;
    attendanceStudent.innerHTML = '<option value="">Choose student</option>' +
      students.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
    attendanceStudent.value = selectedStudent;
    renderAttendanceGrid(month, d);

    const scheduleStudent = $('scheduleStudent');
    const selectedScheduleStudent = scheduleStudent.value;
    scheduleStudent.innerHTML = '<option value="">Choose student</option>' +
      students.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
    scheduleStudent.value = selectedScheduleStudent;
    updateScheduleFields();

    const attendanceLogs = [];
    Object.entries(d.clockTimes).forEach(([studentId, days]) => {
      Object.entries(days).forEach(([day, times]) => {
        attendanceLogs.push({
          student: students.find(s => String(s.id) === studentId)?.name || 'Unknown student',
          date: `${d.year}-${pad(d.month)}-${pad(Number(day))}`,
          times,
          status: (d.records[studentId] || {})[day] || 'Present'
        });
      });
    });
    attendanceLogs.sort((a, b) => b.date.localeCompare(a.date) || a.student.localeCompare(b.student));
    $('attLogTable').innerHTML = attendanceLogs.length
      ? attendanceLogs.map(log => `<tr>
          <td>${esc(log.student)}</td><td>${log.date}</td>
          <td>${esc(log.times.clockIn)}</td><td>${esc(log.times.clockOut || '—')}</td>
          <td>${esc(log.status)}</td>
        </tr>`).join('')
      : '<tr><td colspan="5" class="legend">No attendance records for this month.</td></tr>';
  }

  function renderAttendanceGrid(month, data) {
    const selectedStudentId = $('attendanceStudent').value;
    let h = '<thead><tr><th>Student</th>';
    for (let i = 1; i <= data.days; i++) h += `<th>${i}</th>`;
    h += '</tr></thead><tbody>';

    const student = students.find(s => String(s.id) === selectedStudentId);
    if (!student) {
      h += `<tr><td colspan="${data.days + 1}" class="legend">Choose a student to view attendance.</td></tr>`;
    } else {
      h += `<tr><td>${esc(student.name)}</td>`;
      for (let i = 1; i <= data.days; i++) {
        const status = (data.records[student.id] || {})[i] || '';
        const times = (data.clockTimes[student.id] || {})[i];
        const title = times
          ? ` title="Clock in: ${esc(times.clockIn)}${times.clockOut ? `; Clock out: ${esc(times.clockOut)}` : '; Clock out: not recorded'}"`
          : '';
        const date = `${month}-${pad(i)}`;
        h += `<td class="cell ${status ? SYMBOL[status][0] : ''}" data-sid="${student.id}" data-date="${date}" data-status="${status}"${title}>${status ? SYMBOL[status][1] : '·'}</td>`;
      }
      h += '</tr>';
    }
    $('attTable').innerHTML = h + '</tbody>';
  }

  $('attendanceStudent')?.addEventListener('change', () => {
    if (attendanceData) renderAttendanceGrid($('attMonth').value, attendanceData);
  });

  $('attMonth')?.addEventListener('change', loadAttendance);

  function updateScheduleFields() {
    const schedule = attendanceSchedules.get($('scheduleStudent').value);
    $('scheduleStart').value = schedule?.startTime || '';
    $('scheduleEnd').value = schedule?.endTime || '';
    $('saveSchedule').disabled = !$('scheduleStudent').value;
  }

  $('scheduleStudent')?.addEventListener('change', updateScheduleFields);
  $('attScheduleTable')?.addEventListener('click', async e => {
    const button = e.target.closest('#saveSchedule');
    if (!button) return;
    const studentId = $('scheduleStudent').value;
    const startTime = $('scheduleStart').value;
    const endTime = $('scheduleEnd').value;
    if (!studentId) {
      showToast('Choose a student first.', 'error');
      return;
    }
    if (!startTime || !endTime) {
      showToast('Choose both a start time and an end time.', 'error');
      return;
    }

    button.disabled = true;
    const result = await api('/api/admin/attendance/schedules', 'POST', {
      student_id: studentId,
      start_time: startTime,
      end_time: endTime
    });
    button.disabled = false;
    if (result) {
      attendanceSchedules.set(studentId, {studentId: Number(studentId), startTime, endTime});
      showToast('Student attendance schedule saved.');
    }
  });

  // --- TASKS ---
  async function loadTasks() {
    await loadStudents();
    const sel = $('taskStudent'), keep = sel.value;
    sel.innerHTML = '<option value="">Choose student</option>' + students.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
    sel.value = keep;
    
    const tasks = await api('/api/admin/tasks');
    if (!tasks) return;
    
    $('taskBody').innerHTML = tasks.length ? tasks.map(t => {
      let badgeClass = 'Open';
      let badgeText = 'Open';
      
      if (t.status === 'completed') { badgeClass = 'Done'; badgeText = 'Done'; }
      else if (t.status === 'in_progress') { badgeClass = 'Open'; badgeText = 'In Progress'; }
      else if (t.status === 'pending_approval') { badgeClass = 'Pending'; badgeText = 'Needs Approval'; }

      let actions = '';
      if (t.status === 'pending_approval') {
        // Waiting for student to stop timer -> Show Approve/Reject
        actions = `<button class="btn ok sm" data-approve="${t.id}">Approve</button>
                   <button class="btn no sm" data-reject="${t.id}">Reject</button>`;
      } else if (t.status === 'pending' || t.status === 'in_progress') {
        // Open task -> Show Mark Done / Delete
        actions = `<button class="btn ok sm" data-approve="${t.id}">Mark Done</button>
                   <button class="btn no sm" data-del="${t.id}">Delete</button>`;
      } else {
        // Already completed -> Just Delete
        actions = `<button class="btn no sm" data-del="${t.id}">Delete</button>`;
      }

      return `<tr>
        <td>${esc(t.title)}<br><span class="legend">${esc(t.student)}</span></td>
        <td>${t.due}</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
        <td>${actions}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4" class="legend" style="text-align:center;">No tasks assigned.</td></tr>';
  }
  
  $('taskForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    const r = await api('/api/admin/tasks', 'POST', {
      student_id: $('taskStudent').value, title: $('taskTitle').value,
      description: $('taskDescription').value, due_date: $('taskDue').value
    });
    if (r) { showToast('Task assigned.'); e.target.reset(); loadTasks(); }
  });
  
  $('taskBody')?.addEventListener('click', async e => {
    const btnApprove = e.target.closest('[data-approve]');
    const btnReject = e.target.closest('[data-reject]');
    const btnDelete = e.target.closest('[data-del]');

    if (btnApprove) {
      btnApprove.disabled = true;
      if (await api(`/api/admin/tasks/${btnApprove.dataset.approve}/approve`, 'POST')) {
        showToast('Task approved and marked completed.'); loadTasks();
      }
    } 
    else if (btnReject) {
      btnReject.disabled = true;
      if (await api(`/api/admin/tasks/${btnReject.dataset.reject}/reject`, 'POST')) {
        showToast('Task rejected and sent back to student.', 'error'); loadTasks();
      }
    }
    else if (btnDelete) {
      if (!confirm('Delete this task permanently?')) return;
      if (await api(`/api/admin/tasks/${btnDelete.dataset.del}/delete`, 'POST')) { 
        showToast('Task deleted.'); loadTasks(); 
      }
    }
  });

  // --- HOLIDAYS ---
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
  
  $('prev')?.addEventListener('click', () => { holView.setMonth(holView.getMonth() - 1); renderHolidays(); });
  $('next')?.addEventListener('click', () => { holView.setMonth(holView.getMonth() + 1); renderHolidays(); });
  
  $('holGrid')?.addEventListener('click', async e => {
    const c = e.target.closest('.day[data-date]');
    if (!c) return;
    const date = c.dataset.date;
    if (holidays[date]) {
      if (!confirm(`Remove "${holidays[date]}" on ${date}?`)) return;
      if (await api('/api/admin/holidays', 'DELETE', {date})) { delete holidays[date]; showToast('Holiday removed.'); renderHolidays(); }
    } else {
      const name = prompt(`Holiday name for ${date}:`);
      if (!name || !name.trim()) return;
      if (await api('/api/admin/holidays', 'POST', {date, name: name.trim()})) { holidays[date] = name.trim(); showToast('Holiday added.'); renderHolidays(); }
    }
  });

  // --- STUDENTS (MODAL & SEARCH) ---
  async function loadStudentsPage() {
    const rows = await api('/api/admin/student-list');
    if (!rows) return;
    stuRows = rows;
    renderStudentsTable(stuRows);
  }

  function renderStudentsTable(data) {
    $('stuBody').innerHTML = data.length ? data.map(s => `<tr>
      <td>${esc(s.firstname)} ${esc(s.lastname)}</td><td>${esc(s.email)}</td><td>${esc(s.city)}</td>
      <td><button class="btn ghost sm" data-edit="${s.id}"><i class="fa-solid fa-pen"></i></button><button class="btn no sm" data-rm="${s.id}"><i class="fa-solid fa-trash"></i></button></td></tr>`).join('')
      : '<tr><td colspan="4" class="legend" style="text-align:center;">No students found.</td></tr>';
  }

  // Search functionality
  $('studentSearch')?.addEventListener('input', e => {
    const term = e.target.value.toLowerCase();
    const filtered = stuRows.filter(s => 
      s.firstname.toLowerCase().includes(term) || 
      s.lastname.toLowerCase().includes(term) || 
      s.email.toLowerCase().includes(term)
    );
    renderStudentsTable(filtered);
  });

  // Modal Open/Close
  function openStudentModal(isEdit, student = null) {
    $('studentModal').classList.add('active');
    $('stuForm').reset();
    editId = null;
    
    if (isEdit) {
      editId = student.id;
      $('stuFormTitle').textContent = 'Edit Student';
      $('sFirst').value = student.firstname; $('sLast').value = student.lastname; 
      $('sEmail').value = student.email; $('sMobile').value = student.mobile_no; 
      $('sGender').value = student.gender; $('sDob').value = student.dob; $('sCity').value = student.city;
    } else {
      $('stuFormTitle').textContent = 'Add Student';
    }
  }

  function closeStudentModal() {
    $('studentModal').classList.remove('active');
  }

  $('btnAddStudent')?.addEventListener('click', () => openStudentModal(false));
  $('closeModalBtn')?.addEventListener('click', closeStudentModal);
  $('cancelStuBtn')?.addEventListener('click', closeStudentModal);

  // Table Edit/Delete Actions
  $('stuBody')?.addEventListener('click', async e => {
    const ed = e.target.closest('[data-edit]'), rm = e.target.closest('[data-rm]');
    if (ed) {
      const s = stuRows.find(x => String(x.id) === ed.dataset.edit);
      openStudentModal(true, s);
    } else if (rm) {
      if (!confirm('Delete this student? Their records will also be deleted.')) return;
      if (await api(`/api/admin/student-list/${rm.dataset.rm}`, 'DELETE')) {
        showToast('Student deleted.'); 
        students = []; 
        loadStudentsPage();
      }
    }
  });

  // Form Submit
  $('stuForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    const body = {
      firstname: $('sFirst').value, lastname: $('sLast').value, 
      email: $('sEmail').value, mobile_no: $('sMobile').value,
      gender: $('sGender').value, dob: $('sDob').value, city: $('sCity').value
    };
    
    const r = editId
      ? await api(`/api/admin/student-list/${editId}`, 'PUT', body)
      : await api('/api/admin/student-list', 'POST', body);
      
    if (r) { 
      showToast(editId ? 'Student updated.' : 'Student added.'); 
      closeStudentModal();
      students = []; 
      loadStudentsPage(); 
    }
  });

  // --- CHANGE PASSWORD ---
  $('pwForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    const r = await api('/api/change_password', 'POST', {
      current_password: $('curPw').value, new_password: $('newPw').value, confirm_password: $('confPw').value
    });
    if (r) { showToast('Password updated successfully.'); e.target.reset(); }
  });

  // --- INIT ---
  if($('todayLabel')) $('todayLabel').textContent = now.toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  if($('attMonth')) $('attMonth').value = now.getFullYear() + '-' + pad(now.getMonth() + 1);
  loadDashboard();
})();