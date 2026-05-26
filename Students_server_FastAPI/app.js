'use strict';

// ================================================================
//  STATE
// ================================================================
const S = {
  token: null, role: null, userId: null, username: null,
  groups: [], students: [], teachers: [], courses: [], groupCourses: [], schedules: [],
  att: { skip: 0, limit: 50, total: 0, search: '' },
  cpag: { students:1, teachers:1, groups:1, courses:1, gc:1, schedules:1 },
  filtered: { students:[], teachers:[], groups:[], courses:[], gc:[], schedules:[] },
  PER_PAGE: 40,
  currentSection: 'dashboard',
  modalCallback: null
};

// ================================================================
//  API HELPER
// ================================================================
async function api(method, path, body, queryParams) {
  let url = path;
  if (queryParams) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(queryParams))
      if (v !== null && v !== undefined && v !== '') p.append(k, v);
    const qs = p.toString();
    if (qs) url += '?' + qs;
  }
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (S.token) opts.headers['Authorization'] = 'Bearer ' + S.token;
  if (body !== undefined && body !== null) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (resp.status === 204) return {};
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.detail || `HTTP ${resp.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

// ================================================================
//  AUTH
// ================================================================
function parseJWT(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

async function doLogin() {
  const user = $v('l-user'), pass = document.getElementById('l-pass').value;
  const errEl = document.getElementById('login-error');
  errEl.style.display = 'none';
  if (!user || !pass) { showLoginErr('Попълнете всички полета.'); return; }
  const btn = document.getElementById('login-btn');
  btn.disabled = true; btn.textContent = 'Влизане…';
  try {
    const form = new FormData();
    form.append('username', user); form.append('password', pass);
    const resp = await fetch('/auth/login', { method: 'POST', body: form });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Грешни данни');
    const payload = parseJWT(data.access_token);
    S.token = data.access_token; S.role = payload.role;
    S.userId = payload.user_id; S.username = payload.sub;
    localStorage.setItem('tu_token', S.token);
    await initApp();
  } catch(e) { showLoginErr(e.message); }
  finally { btn.disabled = false; btn.textContent = 'Вход в системата'; }
  function showLoginErr(m) { errEl.textContent = m; errEl.style.display = 'block'; }
}

function doLogout() {
  S.token = S.role = S.userId = S.username = null;
  localStorage.removeItem('tu_token');
  document.getElementById('app').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
}

// ================================================================
//  INIT
// ================================================================
async function initApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app').style.display = 'flex';
  const roleLabels = { admin: 'Администратор', teacher: 'Преподавател', student: 'Студент' };
  document.getElementById('sb-avatar').textContent = S.username[0].toUpperCase();
  document.getElementById('sb-uname').textContent = S.username;
  document.getElementById('sb-urole').textContent = roleLabels[S.role] || S.role;
  buildSidebar();
  await loadRefData();
  nav(S.role === 'student' ? 'attendance' : S.role === 'teacher' ? 'schedules' : 'dashboard');
}

// ================================================================
//  SIDEBAR
// ================================================================
const SIDEBAR_CFG = {
  admin: [
    { lbl: 'Общ преглед', items: [{ id: 'dashboard', icon: '📊', label: 'Табло' }] },
    { lbl: 'Потребители', items: [
      { id: 'students', icon: '👨‍🎓', label: 'Студенти' },
      { id: 'teachers', icon: '👨‍🏫', label: 'Преподаватели' },
      { id: 'admins',   icon: '🔐', label: 'Администратори' }
    ]},
    { lbl: 'Учебен процес', items: [
      { id: 'groups',    icon: '👥', label: 'Групи' },
      { id: 'courses',   icon: '📚', label: 'Дисциплини' },
      { id: 'gc',        icon: '📋', label: 'Учебен план' },
      { id: 'schedules', icon: '📅', label: 'Разписание' }
    ]},
    { lbl: 'Присъствия', items: [{ id: 'attendance', icon: '✅', label: 'Регистър' }] }
  ],
  teacher: [
    { lbl: 'Моите часове', items: [{ id: 'schedules', icon: '📅', label: 'Разписание' }] },
    { lbl: 'Присъствия', items: [
      { id: 'attendance', icon: '✅', label: 'Регистър' },
      { id: 'add-att',    icon: '➕', label: 'Добави ръчно' }
    ]}
  ],
  student: [
    { lbl: 'Моите данни', items: [{ id: 'attendance', icon: '✅', label: 'Моите присъствия' }] }
  ]
};

function buildSidebar() {
  const navEl = document.getElementById('sb-nav');
  navEl.innerHTML = '';
  (SIDEBAR_CFG[S.role] || []).forEach(grp => {
    const lbl = document.createElement('div');
    lbl.className = 'sb-group-lbl'; lbl.textContent = grp.lbl;
    navEl.appendChild(lbl);
    grp.items.forEach(item => {
      const el = document.createElement('div');
      el.className = 'sb-item'; el.id = 'nav-' + item.id;
      el.innerHTML = `<span class="sb-icon">${item.icon}</span><span>${item.label}</span>`;
      el.onclick = () => { nav(item.id); closeSidebar(); };
      navEl.appendChild(el);
    });
  });
}

function nav(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.sb-item').forEach(s => s.classList.remove('active'));
  const sec = document.getElementById('section-' + id);
  if (sec) sec.classList.add('active');
  const ni = document.getElementById('nav-' + id);
  if (ni) ni.classList.add('active');
  S.currentSection = id;
  document.getElementById('content-area').scrollTop = 0;
  renderSection(id);
}

function renderSection(id) {
  ({ dashboard: renderDashboard, students: renderStudents, teachers: renderTeachers,
     groups: renderGroups, courses: renderCourses, gc: renderGC,
     schedules: renderSchedules, attendance: renderAttendance, 'add-att': renderAddAtt
  }[id] || (() => {}))();
}

// ================================================================
//  MOBILE SIDEBAR
// ================================================================
function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebar-backdrop').classList.add('show');
  document.body.style.overflow = 'hidden';
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-backdrop').classList.remove('show');
  document.body.style.overflow = '';
}

// ================================================================
//  LOAD REFERENCE DATA
// ================================================================
async function loadRefData() {
  try {
    if (S.role === 'admin' || S.role === 'teacher') {
      await Promise.all([
        api('GET', '/auth/groups').then(d => S.groups = d),
        api('GET', '/auth/students').then(d => S.students = d),
        api('GET', '/auth/teachers').then(d => S.teachers = d),
        api('GET', '/admin/courses').then(d => S.courses = d),
        api('GET', '/admin/group-courses').then(d => S.groupCourses = d),
        api('GET', '/admin/schedules').then(d => S.schedules = d),
      ]);
    }
    S.filtered.students  = [...S.students];
    S.filtered.teachers  = [...S.teachers];
    S.filtered.groups    = [...S.groups];
    S.filtered.courses   = [...S.courses];
    S.filtered.gc        = [...S.groupCourses];
    S.filtered.schedules = [...S.schedules];
  } catch(e) { toast('Грешка при зареждане: ' + e.message, 'error'); }
}

// ================================================================
//  HELPERS
// ================================================================
const DAY_NAMES  = ['Понеделник','Вторник','Сряда','Четвъртък','Петък','Събота','Неделя'];
const TYPE_MAP   = { lecture: 'Лекция', exercise: 'Упражнение', lab: 'Лаборатория' };

const getGroup  = id => S.groups.find(g => g.id === id) || { name:'?', year:'?', major:'?' };
const getCourse = id => S.courses.find(c => c.id === id) || { name: '?' };
const getTeacher= id => id ? S.teachers.find(t => t.id === id) : null;
const getGC     = id => S.groupCourses.find(g => g.id === id);
const getStusByGroup = gid => S.students.filter(s => s.group_id === gid);
const typeName  = t => TYPE_MAP[t] || t;

// Micro helpers
const $v  = id => (document.getElementById(id)?.value?.trim() || '');
const $iv = id => parseInt(document.getElementById(id)?.value) || 0;

function typeBadge(t) {
  const cls = { lecture:'badge-navy', exercise:'badge-blue', lab:'badge-amber' }[t] || 'badge-gray';
  return `<span class="badge ${cls}">${typeName(t)}</span>`;
}
function statusBadge(s) {
  if (s === 'Присъствие') return `<span class="badge badge-green">✓ Присъствие</span>`;
  if (s === 'Отработване') return `<span class="badge badge-amber">↺ Отработване</span>`;
  if (s === 'Извинено')   return `<span class="badge badge-blue">📋 Извинено</span>`;
  return `<span class="badge badge-gray">${s}</span>`;
}
function scheduleLabel(s) {
  if (!s) return '?';
  const gc = getGC(s.group_course_id);
  if (!gc) return `Разп. #${s.id}`;
  return `${getCourse(gc.course_id).name} [${typeName(gc.type)}] – ${getGroup(gc.group_id).name} – ${DAY_NAMES[s.day_of_week]} ${s.start_time}–${s.end_time} (${s.room_number})`;
}
function fmtDate(d) { return d ? d.substring(0, 10) : '—'; }
function fmtDT(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleDateString('bg-BG', { day:'2-digit', month:'2-digit', year:'numeric' }) + ' ' +
         d.toLocaleTimeString('bg-BG', { hour:'2-digit', minute:'2-digit' });
}

// ================================================================
//  CLIENT PAGINATION
// ================================================================
function slicePage(arr, key) {
  const p = S.cpag[key] || 1;
  return arr.slice((p - 1) * S.PER_PAGE, p * S.PER_PAGE);
}

function buildPag(cont, arr, key, renderFn) {
  if (!cont) return;
  cont.innerHTML = '';
  const total = arr.length, pp = S.PER_PAGE;
  const pages = Math.max(1, Math.ceil(total / pp));
  const cur = S.cpag[key] || 1;
  if (pages <= 1) {
    cont.innerHTML = `<span class="pagination-info">Общо: ${total}</span>`;
    return;
  }
  const wrap = document.createElement('div'); wrap.className = 'pagination';
  const info = document.createElement('span'); info.className = 'pagination-info';
  info.textContent = `${(cur-1)*pp+1}–${Math.min(cur*pp, total)} от ${total}`;
  wrap.appendChild(info);
  const mk = (lbl, dis, act, fn) => {
    const b = document.createElement('span');
    b.className = 'pag-btn' + (dis ? ' disabled' : '') + (act ? ' active' : '');
    b.textContent = lbl; if (!dis) b.onclick = fn; return b;
  };
  wrap.appendChild(mk('‹', cur <= 1, false, () => { S.cpag[key] = cur - 1; renderFn(); }));
  let lo = Math.max(1, cur - 2), hi = Math.min(pages, cur + 2);
  if (lo > 1) { const e = document.createElement('span'); e.className='pag-btn disabled'; e.textContent='…'; wrap.appendChild(e); }
  for (let p = lo; p <= hi; p++) { const pp2=p; wrap.appendChild(mk(p, false, p===cur, ()=>{S.cpag[key]=pp2;renderFn();})); }
  if (hi < pages) { const e = document.createElement('span'); e.className='pag-btn disabled'; e.textContent='…'; wrap.appendChild(e); }
  wrap.appendChild(mk('›', cur >= pages, false, () => { S.cpag[key] = cur + 1; renderFn(); }));
  cont.appendChild(wrap);
}

// ================================================================
//  DASHBOARD
// ================================================================
function renderDashboard() {
  const el = document.getElementById('dash-stats');
  if (S.role === 'admin') {
    el.innerHTML = `
      <div class="stat-card"><div class="stat-icon si-navy">👨‍🎓</div><div><div class="stat-val">${S.students.length}</div><div class="stat-lbl">Студенти</div></div></div>
      <div class="stat-card"><div class="stat-icon si-gold">👨‍🏫</div><div><div class="stat-val">${S.teachers.length}</div><div class="stat-lbl">Преподаватели</div></div></div>
      <div class="stat-card"><div class="stat-icon si-green">👥</div><div><div class="stat-val">${S.groups.length}</div><div class="stat-lbl">Групи</div></div></div>
      <div class="stat-card"><div class="stat-icon si-blue">📚</div><div><div class="stat-val">${S.courses.length}</div><div class="stat-lbl">Дисциплини</div></div></div>
      <div class="stat-card"><div class="stat-icon si-navy">📅</div><div><div class="stat-val">${S.schedules.length}</div><div class="stat-lbl">Занятия</div></div></div>`;
  } else if (S.role === 'teacher') {
    el.innerHTML = `<div class="stat-card"><div class="stat-icon si-navy">📅</div><div><div class="stat-val">${S.schedules.length}</div><div class="stat-lbl">Мои занятия</div></div></div>`;
  } else { el.innerHTML = ''; }
}

// ================================================================
//  STUDENTS
// ================================================================
function filterStudents() {
  const q = $v('stu-search').toLowerCase();
  S.filtered.students = S.students.filter(s => s.name.toLowerCase().includes(q) || s.faculty_number.toLowerCase().includes(q));
  S.cpag.students = 1; renderStudents();
}
function renderStudents() {
  const arr = S.filtered.students, page = slicePage(arr, 'students');
  const tbody = document.getElementById('stu-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="8">Няма намерени студенти.</td></tr>'; return; }
  tbody.innerHTML = page.map(s => {
    const g = getGroup(s.group_id);
    return `<tr>
      <td class="td-id">${s.student_id}</td>
      <td><span class="chip">${s.faculty_number}</span></td>
      <td><strong>${s.name}</strong></td>
      <td style="font-size:12px;color:var(--txt3)">${s.rfid_uid || '—'}</td>
      <td>${g.name}</td><td>${g.year} курс</td><td>${g.major}</td>
      <td><div class="td-actions"><button class="btn btn-ghost btn-sm btn-icon" onclick="openStudentModal(${s.student_id})">✏️</button></div></td>
    </tr>`;
  }).join('');
  buildPag(document.getElementById('stu-pag'), arr, 'students', renderStudents);
}
function openStudentModal(id) {
  const s = id ? S.students.find(x => x.student_id === id) : null, isEdit = !!s;
  document.getElementById('modal-title').textContent = isEdit ? 'Редактиране на студент' : 'Регистрация на нов студент';
  if (isEdit) {
    const g = getGroup(s.group_id);
    document.getElementById('modal-body').innerHTML = `<div class="form-grid">
      <div class="form-group"><label>Пълно Им.</label><input id="sf-name" value="${s.name}"/></div>
      <div class="form-group"><label>Факулт. №</label><input id="sf-fn" value="${s.faculty_number}"/></div>
      <div class="form-group"><label>RFID UID</label><input id="sf-rfid" value="${s.rfid_uid||''}"/></div>
      <div class="form-group"><label>Група</label><input id="sf-gname" value="${g.name}"/></div>
      <div class="form-group"><label>Курс (1–5)</label><input type="number" id="sf-gyear" value="${g.year}" min="1" max="5"/></div>
      <div class="form-group"><label>Специалност</label><input id="sf-gmajor" value="${g.major}"/></div>
    </div>`;
    S.modalCallback = async () => {
      const p = {};
      const nm=$v('sf-name'),fn=$v('sf-fn'),rfid=$v('sf-rfid'),gn=$v('sf-gname'),gy=$iv('sf-gyear'),gm=$v('sf-gmajor');
      if(nm) p.name=nm; if(fn) p.faculty_number=fn; if(rfid) p.rfid_uid=rfid;
      if(gn) p.group_name=gn; if(gy) p.group_year=gy; if(gm) p.group_major=gm;
      await api('PATCH', `/auth/students/${id}`, p);
      await loadRefData(); filterStudents(); toast('Студентът е обновен.', 'success');
    };
  } else {
    document.getElementById('modal-body').innerHTML = `<div class="form-grid">
      <div class="form-group"><label>Потр. Им.</label><input id="sf-user" placeholder="ivan.petrov"/></div>
      <div class="form-group"><label>Парола</label><input type="password" id="sf-pass"/></div>
      <div class="form-group"><label>Пълно Им.</label><input id="sf-name" placeholder="Иван Петров"/></div>
      <div class="form-group"><label>Факулт. №</label><input id="sf-fn" placeholder="221212001"/></div>
      <div class="form-group"><label>RFID UID</label><input id="sf-rfid" placeholder="(незадълж.)"/></div>
      <div class="form-group"><label>Група</label><input id="sf-gname" placeholder="ИУ-1" list="grp-dl"/>
        <datalist id="grp-dl">${S.groups.map(g=>`<option value="${g.name}">`).join('')}</datalist></div>
      <div class="form-group"><label>Курс (1–5)</label><input type="number" id="sf-gyear" value="1" min="1" max="5"/></div>
      <div class="form-group"><label>Специалност</label><input id="sf-gmajor" placeholder="КСТ" list="maj-dl"/>
        <datalist id="maj-dl">${[...new Set(S.groups.map(g=>g.major))].map(m=>`<option value="${m}">`).join('')}</datalist></div>
      <p class="form-hint form-full">Ако групата не съществува, ще бъде създадена автоматично.</p>
    </div>`;
    S.modalCallback = async () => {
      await api('POST', '/auth/register/student', {
        username:$v('sf-user'), password:document.getElementById('sf-pass').value,
        name:$v('sf-name'), faculty_number:$v('sf-fn'), rfid_uid:$v('sf-rfid')||undefined,
        group_name:$v('sf-gname'), group_year:$iv('sf-gyear'), group_major:$v('sf-gmajor')
      });
      await loadRefData(); filterStudents(); toast('Студентът е регистриран.', 'success');
    };
  }
  showModal();
}

// ================================================================
//  TEACHERS
// ================================================================
function filterTeachers() {
  const q = $v('tch-search').toLowerCase();
  S.filtered.teachers = S.teachers.filter(t => t.name.toLowerCase().includes(q) || (t.department||'').toLowerCase().includes(q));
  S.cpag.teachers = 1; renderTeachers();
}
function renderTeachers() {
  const arr = S.filtered.teachers, page = slicePage(arr, 'teachers');
  const tbody = document.getElementById('tch-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="5">Няма намерени преподаватели.</td></tr>'; return; }
  tbody.innerHTML = page.map(t => `<tr>
    <td class="td-id">${t.id}</td>
    <td style="color:var(--txt3);font-size:13px">${t.title||'—'}</td>
    <td><strong>${t.name}</strong></td>
    <td>${t.department||'—'}</td>
    <td><div class="td-actions"><button class="btn btn-ghost btn-sm btn-icon" onclick="openTeacherModal(${t.id})">✏️</button></div></td>
  </tr>`).join('');
  buildPag(document.getElementById('tch-pag'), arr, 'teachers', renderTeachers);
}
function openTeacherModal(id) {
  const t = id ? S.teachers.find(x => x.id === id) : null, isEdit = !!t;
  document.getElementById('modal-title').textContent = isEdit ? 'Редактиране на преподавател' : 'Регистрация на преподавател';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    ${!isEdit ? `<div class="form-group"><label>Потр. Им.</label><input id="tf-user" placeholder="d.ivanov"/></div>
    <div class="form-group"><label>Парола</label><input type="password" id="tf-pass"/></div>` : ''}
    <div class="form-group"><label>Пълно Им.</label><input id="tf-name" value="${t?t.name:''}"/></div>
    <div class="form-group"><label>Звание</label><input id="tf-title" value="${t?.title||''}" placeholder="доц. д-р"/></div>
    <div class="form-group form-full"><label>Катедра</label><input id="tf-dept" value="${t?.department||''}"/></div>
  </div>`;
  S.modalCallback = async () => {
    if (isEdit) {
      await api('PATCH', `/auth/teachers/${id}`, { name:$v('tf-name'), title:$v('tf-title')||null, department:$v('tf-dept')||null });
    } else {
      await api('POST', '/auth/register/teacher', { username:$v('tf-user'), password:document.getElementById('tf-pass').value, name:$v('tf-name'), title:$v('tf-title')||undefined, department:$v('tf-dept')||undefined });
    }
    await loadRefData(); filterTeachers(); toast((isEdit?'Преподавателят е обновен.':'Преподавателят е регистриран.'), 'success');
  };
  showModal();
}

// ================================================================
//  ADMINS
// ================================================================
function openAdminModal() {
  document.getElementById('modal-title').textContent = 'Нов администратор';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group"><label>Потр. Им.</label><input id="adm-user" placeholder="admin2"/></div>
    <div class="form-group"><label>Парола</label><input type="password" id="adm-pass"/></div>
  </div>`;
  S.modalCallback = async () => {
    await api('POST', '/auth/register/admin', { username:$v('adm-user'), password:document.getElementById('adm-pass').value });
    toast('Администраторът е създаден.', 'success');
  };
  showModal();
}

// ================================================================
//  GROUPS
// ================================================================
function filterGroups() {
  const q = $v('grp-search').toLowerCase();
  S.filtered.groups = S.groups.filter(g => g.name.toLowerCase().includes(q) || g.major.toLowerCase().includes(q));
  S.cpag.groups = 1; renderGroups();
}
function renderGroups() {
  const arr = S.filtered.groups, page = slicePage(arr, 'groups');
  const tbody = document.getElementById('grp-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Няма намерени групи.</td></tr>'; return; }
  tbody.innerHTML = page.map(g => {
    const sc = S.students.filter(s => s.group_id === g.id).length;
    return `<tr><td class="td-id">${g.id}</td><td><strong>${g.name}</strong></td><td>${g.year} курс</td><td>${g.major}</td>
      <td><span class="badge badge-navy">${sc}</span></td>
      <td><div class="td-actions"><button class="btn btn-ghost btn-sm btn-icon" onclick="openGroupModal(${g.id})">✏️</button></div></td></tr>`;
  }).join('');
  buildPag(document.getElementById('grp-pag'), arr, 'groups', renderGroups);
}
function openGroupModal(id) {
  const g = id ? S.groups.find(x => x.id === id) : null;
  document.getElementById('modal-title').textContent = g ? 'Редактиране на група' : 'Нова група';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group"><label>Название</label><input id="gf-name" value="${g?g.name:''}" placeholder="ИУ-1"/></div>
    <div class="form-group"><label>Курс (1–5)</label><input type="number" id="gf-year" value="${g?g.year:1}" min="1" max="5"/></div>
    <div class="form-group form-full"><label>Специалност</label><input id="gf-major" value="${g?g.major:''}" placeholder="КСТ"/></div>
  </div>`;
  S.modalCallback = async () => {
    const payload = { name:$v('gf-name'), year:$iv('gf-year'), major:$v('gf-major') };
    if (g) await api('PATCH', `/admin/groups/${id}`, payload);
    else await api('POST', '/admin/groups', payload);
    await loadRefData(); filterGroups(); toast((g?'Групата е обновена.':'Групата е създадена.'), 'success');
  };
  showModal();
}

// ================================================================
//  COURSES
// ================================================================
function filterCourses() {
  const q = $v('crs-search').toLowerCase();
  S.filtered.courses = S.courses.filter(c => c.name.toLowerCase().includes(q));
  S.cpag.courses = 1; renderCourses();
}
function renderCourses() {
  const arr = S.filtered.courses, page = slicePage(arr, 'courses');
  const tbody = document.getElementById('crs-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="3">Няма намерени дисциплини.</td></tr>'; return; }
  tbody.innerHTML = page.map(c => `<tr><td class="td-id">${c.id}</td><td>${c.name}</td>
    <td><div class="td-actions"><button class="btn btn-ghost btn-sm btn-icon" onclick="openCourseModal(${c.id})">✏️</button></div></td></tr>`).join('');
  buildPag(document.getElementById('crs-pag'), arr, 'courses', renderCourses);
}
function openCourseModal(id) {
  const c = id ? S.courses.find(x => x.id === id) : null;
  document.getElementById('modal-title').textContent = c ? 'Редактиране на дисциплина' : 'Нова дисциплина';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group form-full"><label>Наименование</label><input id="cf-name" value="${c?c.name:''}" placeholder="Математика I"/></div>
  </div>`;
  S.modalCallback = async () => {
    const payload = { name: $v('cf-name') };
    if (c) await api('PATCH', `/admin/courses/${id}`, payload);
    else await api('POST', '/admin/courses', payload);
    await loadRefData(); filterCourses(); toast((c?'Дисциплината е обновена.':'Дисциплината е създадена.'), 'success');
  };
  showModal();
}

// ================================================================
//  GROUP-COURSES
// ================================================================
function filterGC() {
  const q = $v('gc-search').toLowerCase();
  S.filtered.gc = S.groupCourses.filter(gc => {
    const g=getGroup(gc.group_id), c=getCourse(gc.course_id);
    return g.name.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || g.major.toLowerCase().includes(q);
  });
  S.cpag.gc = 1; renderGC();
}
function renderGC() {
  const arr = S.filtered.gc, page = slicePage(arr, 'gc');
  const tbody = document.getElementById('gc-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Няма записи в учебния план.</td></tr>'; return; }
  tbody.innerHTML = page.map(gc => {
    const g=getGroup(gc.group_id), c=getCourse(gc.course_id), t=getTeacher(gc.teacher_id);
    return `<tr><td class="td-id">${gc.id}</td>
      <td><strong>${g.name}</strong> <span style="color:var(--txt3);font-size:12px">${g.year}к. ${g.major}</span></td>
      <td>${c.name}</td><td>${typeBadge(gc.type)}</td>
      <td>${t?`<span class="chip">${t.title?t.title+' ':''}${t.name}</span>`:'<span style="color:var(--txt3)">—</span>'}</td>
      <td>${gc.semester||'—'}</td>
      <td><div class="td-actions"><button class="btn btn-ghost btn-sm btn-icon" onclick="openGCModal(${gc.id})">✏️</button></div></td></tr>`;
  }).join('');
  buildPag(document.getElementById('gc-pag'), arr, 'gc', renderGC);
}
function openGCModal(id) {
  const gc = id ? S.groupCourses.find(x => x.id === id) : null;
  const grpOpts = S.groups.map(g=>`<option value="${g.id}" ${gc&&gc.group_id===g.id?'selected':''}>${g.name} – ${g.year}к., ${g.major}</option>`).join('');
  const crsOpts = S.courses.map(c=>`<option value="${c.id}" ${gc&&gc.course_id===c.id?'selected':''}>${c.name}</option>`).join('');
  const tchOpts = `<option value="0">— Без преподавател —</option>` + S.teachers.map(t=>`<option value="${t.id}" ${gc&&gc.teacher_id===t.id?'selected':''}>${t.title?t.title+' ':''}${t.name}</option>`).join('');
  const typeOpts = ['lecture','exercise','lab'].map(tp=>`<option value="${tp}" ${gc&&gc.type===tp?'selected':''}>${typeName(tp)}</option>`).join('');
  document.getElementById('modal-title').textContent = gc ? 'Редактиране на зачисляване' : 'Ново зачисляване';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group form-full"><label>Група</label><select id="gcf-grp">${grpOpts}</select></div>
    <div class="form-group form-full"><label>Дисциплина</label><select id="gcf-crs">${crsOpts}</select></div>
    <div class="form-group"><label>Тип</label><select id="gcf-type">${typeOpts}</select></div>
    <div class="form-group"><label>Семестър</label><input type="number" id="gcf-sem" value="${gc?gc.semester||'':''}" min="1" max="10"/></div>
    <div class="form-group form-full"><label>Преподавател</label><select id="gcf-tch">${tchOpts}</select></div>
  </div>`;
  S.modalCallback = async () => {
    const payload = { group_id:parseInt($v('gcf-grp')), course_id:parseInt($v('gcf-crs')), type:$v('gcf-type'), semester:$iv('gcf-sem')||null, teacher_id:parseInt($v('gcf-tch'))||null };
    if (gc) await api('PATCH', `/admin/group-courses/${id}`, payload);
    else await api('POST', '/admin/group-courses', payload);
    await loadRefData(); filterGC(); toast((gc?'Обновено.':'Добавено.'), 'success');
  };
  showModal();
}

// ================================================================
//  SCHEDULES
// ================================================================
function filterSchedules() {
  const q = $v('sched-search').toLowerCase();
  S.filtered.schedules = S.schedules.filter(s => {
    const gc=getGC(s.group_course_id); if(!gc) return false;
    const c=getCourse(gc.course_id), g=getGroup(gc.group_id);
    return c.name.toLowerCase().includes(q) || g.name.toLowerCase().includes(q) || s.room_number.toLowerCase().includes(q) || DAY_NAMES[s.day_of_week].toLowerCase().includes(q);
  });
  S.cpag.schedules = 1; renderSchedules();
}
function renderSchedules() {
  document.getElementById('sched-add-btn').style.display = S.role === 'admin' ? '' : 'none';
  const arr = S.filtered.schedules, page = slicePage(arr, 'schedules');
  const tbody = document.getElementById('sched-tbody');
  if (!arr.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="11">Няма записи в разписанието.</td></tr>'; return; }
  tbody.innerHTML = page.map(s => {
    const gc=getGC(s.group_course_id), c=gc?getCourse(gc.course_id):{name:'?'}, g=gc?getGroup(gc.group_id):{name:'?'};
    return `<tr><td class="td-id">${s.id}</td>
      <td><strong>${c.name}</strong></td><td>${typeBadge(gc?gc.type:'?')}</td>
      <td>${g.name}</td><td><span class="chip">🚪 ${s.room_number}</span></td>
      <td>${DAY_NAMES[s.day_of_week]}</td>
      <td style="white-space:nowrap">${s.start_time}–${s.end_time}</td>
      <td>${s.subgroup||'—'}</td>
      <td><span class="badge ${s.is_biweekly?'badge-amber':'badge-green'}">${s.is_biweekly?'Двуседм.':'Всяка'}</span></td>
      <td style="font-size:12px;color:var(--txt3)">${fmtDate(s.start_date)} → ${fmtDate(s.end_date)}</td>
      <td><div class="td-actions">${S.role==='admin'?`<button class="btn btn-ghost btn-sm btn-icon" onclick="openScheduleModal(${s.id})">✏️</button>`:''}</div></td></tr>`;
  }).join('');
  buildPag(document.getElementById('sched-pag'), arr, 'schedules', renderSchedules);
}
function openScheduleModal(id) {
  const s = id ? S.schedules.find(x => x.id === id) : null;
  const gcOpts = S.groupCourses.map(gc => {
    const c=getCourse(gc.course_id), g=getGroup(gc.group_id);
    return `<option value="${gc.id}" ${s&&s.group_course_id===gc.id?'selected':''}>${c.name} [${typeName(gc.type)}] – ${g.name} ${g.year}к.</option>`;
  }).join('');
  const dayOpts = DAY_NAMES.map((d,i) => `<option value="${i}" ${s&&s.day_of_week===i?'selected':''}>${d}</option>`).join('');
  document.getElementById('modal-title').textContent = s ? 'Редактиране на запис' : 'Ново занятие';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group form-full"><label>Занятие (Учебен план)</label><select id="sf2-gc">${gcOpts}</select></div>
    <div class="form-group"><label>Зала</label><input id="sf2-room" value="${s?s.room_number:''}" placeholder="А301"/></div>
    <div class="form-group"><label>Ден</label><select id="sf2-day">${dayOpts}</select></div>
    <div class="form-group"><label>Нач. час</label><input type="time" id="sf2-start" value="${s?s.start_time:'08:00'}"/></div>
    <div class="form-group"><label>Кр. час</label><input type="time" id="sf2-end" value="${s?s.end_time:'10:00'}"/></div>
    <div class="form-group"><label>Подгрупа</label><input id="sf2-sg" value="${s?.subgroup||''}" placeholder="А, Б…"/></div>
    <div class="form-group"><label>Повторяемост</label>
      <select id="sf2-biw"><option value="false" ${!s||!s.is_biweekly?'selected':''}>Всяка седмица</option><option value="true" ${s?.is_biweekly?'selected':''}>Двуседмично</option></select></div>
    <div class="form-group"><label>Начална дата</label><input type="date" id="sf2-sd" value="${s?s.start_date:''}"/></div>
    <div class="form-group"><label>Крайна дата</label><input type="date" id="sf2-ed" value="${s?s.end_date:''}"/></div>
  </div>`;
  S.modalCallback = async () => {
    const payload = { room_number:$v('sf2-room'), day_of_week:parseInt($v('sf2-day')), start_time:$v('sf2-start'), end_time:$v('sf2-end'), subgroup:$v('sf2-sg')||null, is_biweekly:$v('sf2-biw')==='true', start_date:$v('sf2-sd'), end_date:$v('sf2-ed') };
    if (s) await api('PATCH', `/admin/schedules/${id}`, payload);
    else { payload.group_course_id = parseInt($v('sf2-gc')); await api('POST', '/admin/schedules', payload); }
    await loadRefData(); filterSchedules(); toast((s?'Разписанието е обновено.':'Занятието е добавено.'), 'success');
  };
  showModal();
}

// ================================================================
//  ATTENDANCE  (server-side pagination)
// ================================================================
let _attDeb = null;
function debouncedAttSearch() {
  clearTimeout(_attDeb);
  _attDeb = setTimeout(() => { S.att.search = $v('att-search'); S.att.skip = 0; renderAttendance(); }, 350);
}
function attChangePerPage() {
  S.att.limit = parseInt(document.getElementById('att-per-page').value);
  S.att.skip = 0; renderAttendance();
}
async function renderAttendance() {
  const canEdit = S.role === 'admin' || S.role === 'teacher';
  document.getElementById('att-add-btn').style.display = canEdit ? '' : 'none';
  document.getElementById('att-actions-th').textContent = canEdit ? 'Дейности' : '';
  const tbody = document.getElementById('att-tbody');
  tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Зареждане…</td></tr>';
  try {
    const data = await api('GET', '/attendance', null, { skip:S.att.skip, limit:S.att.limit, search:S.att.search||undefined });
    S.att.total = data.total;
    tbody.innerHTML = data.items.length
      ? data.items.map(a => `<tr>
          <td class="td-id">${a.id}</td>
          <td style="white-space:nowrap;font-size:13px">${fmtDT(a.timestamp)}</td>
          <td>${a.student_name}</td><td>${a.course_name}</td>
          <td>${statusBadge(a.status)}</td>
          <td><span class="badge badge-gray" style="font-size:11px">${a.recorded_by}</span></td>
          <td>${canEdit?`<div class="td-actions">
            <button class="btn btn-ghost btn-sm btn-icon" onclick="editAttStatus(${a.id},'${a.status}')">✏️</button>
            <button class="btn btn-danger btn-sm btn-icon" onclick="deleteAtt(${a.id})">🗑️</button>
          </div>`:''}</td>
        </tr>`).join('')
      : '<tr class="empty-row"><td colspan="7">Няма намерени записи.</td></tr>';
    buildAttPag();
  } catch(e) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="7" style="color:var(--red)">Грешка: ${e.message}</td></tr>`;
  }
}
function buildAttPag() {
  const cont = document.getElementById('att-pag'); cont.innerHTML = '';
  const { total, limit, skip } = S.att;
  if (!total) return;
  const pages = Math.max(1, Math.ceil(total/limit)), cur = Math.floor(skip/limit)+1;
  const wrap = document.createElement('div'); wrap.className = 'pagination';
  const info = document.createElement('span'); info.className = 'pagination-info';
  info.textContent = `${skip+1}–${Math.min(skip+limit,total)} от ${total} записа`;
  wrap.appendChild(info);
  const mk = (lbl,dis,act,fn)=>{const b=document.createElement('span');b.className='pag-btn'+(dis?' disabled':'')+(act?' active':'');b.textContent=lbl;if(!dis)b.onclick=fn;return b;};
  wrap.appendChild(mk('‹',cur<=1,false,()=>{S.att.skip=Math.max(0,skip-limit);renderAttendance();}));
  let lo=Math.max(1,cur-2),hi=Math.min(pages,cur+2);
  if(lo>1){const e=document.createElement('span');e.className='pag-btn disabled';e.textContent='…';wrap.appendChild(e);}
  for(let p=lo;p<=hi;p++){const pp=p;wrap.appendChild(mk(p,false,p===cur,()=>{S.att.skip=(pp-1)*limit;renderAttendance();}));}
  if(hi<pages){const e=document.createElement('span');e.className='pag-btn disabled';e.textContent='…';wrap.appendChild(e);}
  wrap.appendChild(mk('›',cur>=pages,false,()=>{S.att.skip=skip+limit;renderAttendance();}));
  cont.appendChild(wrap);
}
function editAttStatus(id, curr) {
  const opts = ['Присъствие','Отработване','Извинено'].map(s=>`<option value="${s}" ${s===curr?'selected':''}>${s}</option>`).join('');
  document.getElementById('modal-title').textContent = 'Промяна на статус';
  document.getElementById('modal-body').innerHTML = `<div class="form-group"><label>Нов статус</label><select id="att-sel">${opts}</select></div>`;
  S.modalCallback = async () => { await api('PATCH', `/attendance/${id}`, { status:$v('att-sel') }); renderAttendance(); toast('Статусът е обновен.','success'); };
  showModal();
}
async function deleteAtt(id) {
  if (!confirm('Изтриване на записа за присъствие?')) return;
  try { await api('DELETE', `/attendance/${id}`); renderAttendance(); toast('Записът е изтрит.','success'); }
  catch(e) { toast(e.message, 'error'); }
}
function openAttAddModal() {
  const gcOpts = S.schedules.map(s=>`<option value="${s.id}">${scheduleLabel(s)}</option>`).join('');
  const stuOpts = S.students.map(s=>`<option value="${s.student_id}">${s.name} (ФН: ${s.faculty_number})</option>`).join('');
  document.getElementById('modal-title').textContent = 'Добавяне на присъствие ръчно';
  document.getElementById('modal-body').innerHTML = `<div class="form-grid">
    <div class="form-group form-full"><label>Занятие</label><select id="ma-sched">${gcOpts}</select></div>
    <div class="form-group form-full"><label>Студент</label><select id="ma-stu">${stuOpts}</select></div>
    <div class="form-group"><label>Дата</label><input type="date" id="ma-date" value="${new Date().toISOString().split('T')[0]}"/></div>
    <div class="form-group"><label>Статус</label>
      <select id="ma-status"><option value="Присъствие">Присъствие</option><option value="Отработване">Отработване</option><option value="Извинено">Извинено</option></select></div>
  </div>`;
  S.modalCallback = async () => {
    await api('POST', '/attendance', null, { student_id:$v('ma-stu'), schedule_id:$v('ma-sched'), status:$v('ma-status'), date:$v('ma-date') });
    renderAttendance(); toast('Присъствието е добавено.', 'success');
  };
  showModal();
}

// ================================================================
//  ADD ATTENDANCE SECTION (Teacher)
// ================================================================
function renderAddAtt() {
  const sel = document.getElementById('fa-sched');
  sel.innerHTML = '<option value="">— Изберете занятие —</option>' + S.schedules.map(s=>`<option value="${s.id}">${scheduleLabel(s)}</option>`).join('');
  document.getElementById('fa-date').value = new Date().toISOString().split('T')[0];
  document.getElementById('fa-result').innerHTML = '';
}
function faSchedChanged() {
  const sid = parseInt($v('fa-sched'));
  const sel = document.getElementById('fa-student');
  if (!sid) { sel.innerHTML = '<option value="">— Изберете занятие първо —</option>'; return; }
  const gc = getGC((S.schedules.find(s => s.id === sid)||{}).group_course_id);
  const stus = gc ? getStusByGroup(gc.group_id) : [];
  sel.innerHTML = stus.length ? stus.map(s=>`<option value="${s.student_id}">${s.name} (ФН: ${s.faculty_number})</option>`).join('') : '<option value="">Няма студенти в тази група</option>';
}
async function submitAddAttendance() {
  const sched_id=$v('fa-sched'), student_id=$v('fa-student'), date=$v('fa-date'), status=$v('fa-status');
  const res = document.getElementById('fa-result');
  if (!sched_id || !student_id || !date) { res.innerHTML='<p class="fa-result-err">Попълнете всички полета.</p>'; return; }
  try {
    await api('POST', '/attendance', null, { student_id, schedule_id:sched_id, status, date });
    res.innerHTML = '<p class="fa-result-ok">✅ Присъствието е записано успешно!</p>';
    toast('Присъствието е добавено.', 'success');
    setTimeout(resetAddAttForm, 2000);
  } catch(e) { res.innerHTML=`<p class="fa-result-err">⚠️ ${e.message}</p>`; }
}
function resetAddAttForm() {
  document.getElementById('fa-sched').value = '';
  document.getElementById('fa-student').innerHTML = '<option value="">— Изберете занятие първо —</option>';
  document.getElementById('fa-date').value = new Date().toISOString().split('T')[0];
  document.getElementById('fa-status').value = 'Присъствие';
  document.getElementById('fa-result').innerHTML = '';
}

// ================================================================
//  MODAL
// ================================================================
function showModal() { document.getElementById('modal-overlay').classList.add('show'); }
function closeModal() { document.getElementById('modal-overlay').classList.remove('show'); S.modalCallback = null; }
function modalOverlayClick(e) { if (e.target === document.getElementById('modal-overlay')) closeModal(); }
async function modalSubmit() {
  if (!S.modalCallback) return;
  const btn = document.getElementById('modal-submit');
  btn.disabled = true; btn.textContent = 'Запазване…';
  try { await S.modalCallback(); closeModal(); }
  catch(e) { toast(e.message, 'error'); }
  finally { btn.disabled = false; btn.textContent = 'Запази'; }
}

// ================================================================
//  TOAST
// ================================================================
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`; el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 320); }, 3500);
}

// ================================================================
//  KEYBOARD & EVENTS
// ================================================================
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'Enter' && document.getElementById('login-screen').style.display !== 'none') doLogin();
});
document.getElementById('hamburger').onclick = openSidebar;
document.getElementById('sidebar-backdrop').onclick = closeSidebar;

// ================================================================
//  AUTO-LOGIN ON LOAD
// ================================================================
window.addEventListener('load', async () => {
  const saved = localStorage.getItem('tu_token');
  if (saved) {
    const payload = parseJWT(saved);
    if (payload && payload.exp * 1000 > Date.now()) {
      S.token = saved; S.role = payload.role; S.userId = payload.user_id; S.username = payload.sub;
      await initApp(); return;
    }
    localStorage.removeItem('tu_token');
  }
  document.getElementById('login-screen').style.display = 'flex';
});