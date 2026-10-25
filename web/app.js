const $ = (s) => document.querySelector(s);
let autoUpdate = true,
  planData = null,
  refreshSeconds = 30,
  failureCount = 0,
  timer = null;
let connected = false,
  csrf = "",
  busy = false,
  meetingsOnly = false,
  selectedId = null,
  desktop = false;
let messages = [
  {
    id: "demo1",
    subject: "Терміново: узгодити план на понеділок",
    from: {
      emailAddress: { name: "Олена Коваль", address: "olena@example.com" },
    },
    bodyPreview:
      "Привіт! Переглянь, будь ласка, пропозицію та напиши, коли зручно обговорити.",
    category: "Від людей",
    priority: "high",
  },
  {
    id: "demo2",
    subject: "Jira · WA-42: завдання готове до перевірки",
    from: { emailAddress: { name: "Jira", address: "jira@example.com" } },
    bodyPreview: "Оновлено статус завдання вашої команди.",
    category: "Jira та Confluence",
    priority: "normal",
  },
  {
    id: "demo3",
    subject: "Confluence · Оновлення бази знань",
    from: {
      emailAddress: { name: "Confluence", address: "confluence@example.com" },
    },
    category: "Jira та Confluence",
    priority: "normal",
  },
  {
    id: "demo4",
    subject: "Навчання: робота з пріоритетами",
    from: { emailAddress: { name: "Learning", address: "learn@example.com" } },
    category: "Навчання",
    priority: "normal",
  },
  {
    id: "demo5",
    subject: "Ваш щотижневий звіт · report.xlsx",
    from: {
      emailAddress: { name: "Сповіщення", address: "noreply@example.com" },
    },
    category: "Звіти",
    priority: "normal",
    hasAttachments: true,
  },
  {
    id: "demo6",
    subject: "Запрошення: планування спринту",
    from: { emailAddress: { name: "Андрій", address: "andriy@example.com" } },
    category: "Від людей",
    priority: "normal",
    meeting: true,
    meetingStatus: "Демо: календар не перевірявся",
  },
];
const labels = { high: "Високий", normal: "Звичайний", low: "Низький" };
function element(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}
function card(m) {
  const c = element("article", "card " + m.priority),
    meta = element("div", "meta");
  meta.append(
    element(
      "span",
      "",
      m.from?.emailAddress?.name ||
        m.from?.emailAddress?.address ||
        "Невідомий відправник",
    ),
  );
  if (m.receivedDateTime)
    meta.append(
      element(
        "span",
        "",
        new Date(m.receivedDateTime).toLocaleDateString("uk-UA"),
      ),
    );
  c.append(
    meta,
    element("h3", "subject", m.subject || "(без теми)"),
    element("div", "preview", (m.bodyPreview || "").slice(0, 220)),
  );
  const tags = element("div", "tags");
  tags.append(
    element("span", "tag", m.category),
    element("span", "tag " + m.priority, labels[m.priority]),
  );
  if (m.meeting)
    tags.append(
      element("span", "tag", m.meetingStatus || "Запрошення на нараду"),
    );
  c.append(tags);
  if (m.webLink) {
    try {
      const u = new URL(m.webLink);
      if (u.protocol === "https:") {
        const a = element("a", "", "Відкрити в Outlook ↗");
        a.href = u.href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        c.append(a);
      }
    } catch {}
  }
  return c;
}
function render() {
  const q = $("#search").value.toLowerCase();
  const list = messages
    .filter(
      (m) =>
        (!meetingsOnly || m.meeting) &&
        (!$("#category").value || m.category === $("#category").value) &&
        (!$("#priority").value || m.priority === $("#priority").value) &&
        `${m.subject} ${m.from?.emailAddress?.name} ${m.from?.emailAddress?.address}`
          .toLowerCase()
          .includes(q),
    )
    .sort(
      (a, b) =>
        ({ high: 0, normal: 1, low: 2 })[a.priority] -
        { high: 0, normal: 1, low: 2 }[b.priority],
    );
  $("#messages").replaceChildren(...list.map(card));
  const people = list.filter((m) => m.category === "Від людей");
  $("#people").replaceChildren(...people.map(card));
  if (!list.length)
    $("#messages").append(element("p", "", "Листів за цими фільтрами немає."));
  if (!people.length)
    $("#people").append(
      element("p", "", "Особистих листів за цими фільтрами немає."),
    );
  $("#count").textContent = list.length;
  document.querySelectorAll("#messages .card").forEach((node, index) => {
    node.dataset.messageId = list[index].id;
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", list[index].subject);
    node.onclick = () => showDetail(list[index]);
    node.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        showDetail(list[index]);
      }
    };
    node.classList.toggle("selected", list[index].id === selectedId);
  });
  document.querySelectorAll("#people .card").forEach((node, index) => {
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.onclick = () => showDetail(people[index]);
    node.onkeydown = (e) => {
      if (e.key === "Enter") {
        showDetail(people[index]);
      }
    };
  });
  const chosen = list.find((m) => m.id === selectedId) || list[0];
  if (chosen) showDetail(chosen);
  else {
    $("#detail").replaceChildren(
      element("h2", "", "Немає листів для перегляду"),
    );
    selectedId = null;
  }
}
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  let r;
  try {
    r = await fetch(
      path,
      body === undefined
        ? { signal: controller.signal }
        : {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrf,
            },
            body: JSON.stringify(body),
            signal: controller.signal,
          },
    );
  } finally {
    clearTimeout(timeout);
  }
  const data = await r.json();
  if (!r.ok) throw Error(data.error || "Помилка запиту");
  return data;
}
async function run(fn) {
  if (busy) return;
  busy = true;
  $("#sync-status").textContent = "Оновлення…";
  $("#error").textContent = "";
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await fn();
  } catch (e) {
    failureCount++;
    $("#error").textContent =
      e.name === "AbortError"
        ? "Сервіс не відповідає. Перевірте мережу та повторіть."
        : e.message;
  } finally {
    $("#sync-status").textContent = "";
    busy = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}
async function refresh() {
  if (!connected) {
    $("#notice").textContent =
      "Демо-режим. Для вашої пошти підключіть Outlook.";
    return;
  }
  const data = await api("/api/messages");
  messages = data.messages;
  render();
  $("#notice").textContent =
    `Завантажено ${messages.length} листів.${data.limited ? " Показано лише 100 останніх." : ""} Перевірка запрошень…`;
  const meetings = await api("/api/meetings", {});
  messages.forEach((m) => (m.meetingStatus = meetings.results[m.id]));
  render();
  $("#notice").textContent =
    `Оновлено ${messages.length} листів.${data.limited ? " Показано лише 100 останніх." : ""} Запрошення перевірено. ${new Date().toLocaleTimeString("uk-UA")}`;
  failureCount = 0;
  await refreshPlan();
}
$("#refresh").onclick = () => run(refresh);
$("#save").onclick = () =>
  run(async () => {
    if (!connected) throw Error("Спочатку підключіть Outlook.");
    if (
      !confirm(
        "Записати категорії та пріоритети для всіх завантажених листів в Outlook?",
      )
    )
      return;
    let done = 0;
    for (const m of messages) {
      await api("/api/categorize", { id: m.id });
      $("#notice").textContent = `Збережено ${++done} із ${messages.length}`;
    }
  });
$("#logout").onclick = () =>
  run(async () => {
    await api("/api/logout", {});
    location.reload();
  });
for (const selector of ["#category", "#priority", "#search"])
  $(selector).addEventListener("input", render);
function showDetail(m) {
  selectedId = m.id;
  const target = $("#detail");
  target.replaceChildren(
    element("span", "eyebrow", "ПЕРЕГЛЯД ЛИСТА"),
    element("h2", "", m.subject || "(без теми)"),
    element(
      "p",
      "",
      `${m.from?.emailAddress?.name || ""} · ${m.from?.emailAddress?.address || ""}`,
    ),
    element("span", "tag " + m.priority, labels[m.priority]),
    element("span", "tag", m.category),
    element(
      "div",
      "body",
      m.bodyPreview || "Текст відсутній. Відкрийте оригінал в Outlook.",
    ),
  );
  if (connected) {
    const controls = element("div", "message-controls");
    const category = element("select");
    category.setAttribute("aria-label", "Категорія листа");
    for (const name of [
      "Від людей",
      "Звіти",
      "Навчання",
      "Автоматичні повідомлення",
      "Jira та Confluence",
    ]) {
      const option = element("option", "", name);
      option.value = name;
      category.append(option);
    }
    category.value = m.category;
    const priority = element("select");
    priority.setAttribute("aria-label", "Пріоритет листа");
    for (const [key, label] of Object.entries(labels)) {
      const option = element("option", "", label);
      option.value = key;
      priority.append(option);
    }
    priority.value = m.priority;
    const save = element("button", "", "Зберегти цей лист в Outlook");
    save.onclick = () =>
      run(async () => {
        await api("/api/override", {
          id: m.id,
          category: category.value,
          priority: priority.value,
        });
        await api("/api/categorize", { id: m.id });
        m.category = category.value;
        m.priority = priority.value;
        render();
      });
    controls.append(category, priority, save);
    target.append(controls);
  }
  if (m.meeting)
    target.append(element("p", "", m.meetingStatus || "Запрошення на нараду"));
  if (connected && desktop) {
    const b = element("button", "", "Відкрити оригінал в Outlook ↗");
    b.onclick = () => run(() => api("/api/open", { id: m.id }));
    target.append(b);
  } else if (m.webLink) {
    try {
      const u = new URL(m.webLink);
      if (u.protocol === "https:") {
        const a = element("a", "", "Відкрити в Outlook ↗");
        a.href = u.href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        target.append(a);
      }
    } catch {}
  }
  document
    .querySelectorAll("#messages .card")
    .forEach((c, i) =>
      c.classList.toggle("selected", c.dataset.messageId === m.id),
    );
}
function showMail() {
  $("#profile-panel").hidden = true;
  $("#plan-panel").hidden = true;
  $(".columns").hidden = false;
  $(".filters").hidden = false;
}
function chooseCategory(value) {
  showMail();
  meetingsOnly = false;
  $("#category").value = value;
  $("#view-title").firstChild.textContent = (value || "Усі вхідні") + " ";
  document
    .querySelectorAll(".nav-item")
    .forEach((b) => b.classList.toggle("active", b.dataset.category === value));
  render();
}
document
  .querySelectorAll("[data-category]")
  .forEach((b) => (b.onclick = () => chooseCategory(b.dataset.category)));
$("#meetings-nav").onclick = () => {
  showMail();
  meetingsOnly = true;
  $("#category").value = "";
  $("#view-title").firstChild.textContent = "Наради ";
  document
    .querySelectorAll(".nav-item")
    .forEach((b) => b.classList.toggle("active", b.id === "meetings-nav"));
  render();
};
$("#category").addEventListener("change", () =>
  chooseCategory($("#category").value),
);
$("#connect").onclick = () =>
  run(async () => {
    await api("/api/connect", {});
    location.reload();
  });
$("#today").textContent = new Date().toLocaleDateString("uk-UA", {
  weekday: "long",
  day: "numeric",
  month: "long",
});
render();
run(async () => {
  const s = await api("/api/status");
  connected = s.connected;
  csrf = s.csrf;
  desktop = s.desktop;
  $("#jira-email").value = s.profile?.email || "";
  $("#jira-url").value = s.profile?.url || "";
  applyPreferences(s.profile || {});
  showTeamsStatus(s.teams || { status: "disconnected" });
  $("#connect").hidden = connected;
  if (connected) {
    $("#connection").textContent = "Outlook підключено";
    $("#logout").hidden = false;
    await refresh();
  } else
    $("#notice").textContent = desktop
      ? "Натисніть «Підключити Outlook», щоб використати ваш поточний профіль."
      : "Демо-режим. Для вашої пошти запустіть Windows-застосунок із класичним Outlook.";
});

function renderPlan() {
  const sources = $("#plan-sources"),
    blocks = $("#plan-blocks"),
    backlog = $("#plan-backlog");
  if (!planData) {
    sources.replaceChildren(
      element(
        "p",
        "",
        "Підключіть Outlook, щоб прочитати календар і скласти графік.",
      ),
    );
    blocks.replaceChildren();
    backlog.replaceChildren();
    return;
  }
  sources.replaceChildren(
    ...Object.entries(planData.sources).map(([name, status]) =>
      element("p", "source-status", name.toUpperCase() + ": " + status),
    ),
  );
  const all = [
    ...planData.meetings.map((e) => ({ ...e, source: "Календар" })),
    ...planData.blocks,
  ].sort((a, b) => new Date(a.start) - new Date(b.start));
  blocks.replaceChildren(
    ...all.map((block) => {
      const card = element("article", "card");
      const date = new Date(block.start),
        end = new Date(block.end);
      card.append(
        element("span", "tag", block.source),
        element("h3", "subject", block.title),
        element(
          "p",
          "",
          date.toLocaleString("uk-UA", { timeZone: planData.timezone }) +
            " — " +
            end.toLocaleTimeString("uk-UA", {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: planData.timezone,
            }),
        ),
      );
      if (block.overdue)
        card.append(element("span", "tag high", "Після дедлайну"));
      if (block.url) {
        try {
          const u = new URL(block.url);
          if (u.protocol === "https:") {
            const a = element("a", "", "Відкрити джерело ↗");
            a.href = u.href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            card.append(a);
          }
        } catch {}
      }
      if (block.source !== "Календар") {
        const dismiss = element("button", "", "Прибрати з плану");
        dismiss.onclick = () =>
          run(async () => {
            await api("/api/task-dismiss", { id: block.id });
            await refreshPlan();
          });
        card.append(dismiss);
      }
      return card;
    }),
  );
  if (!all.length)
    blocks.append(
      element("p", "", "Немає зустрічей чи задач із підключених джерел."),
    );
  backlog.replaceChildren(
    ...planData.backlog.map((t) =>
      element(
        "p",
        "",
        "Не вмістилося: " + t.title + " · " + t.remainingMinutes + " хв",
      ),
    ),
  );
}
async function refreshPlan() {
  try {
    planData = await api("/api/plan");
    renderPlan();
  } catch (e) {
    planData = null;
    renderPlan();
    $("#plan-sources").replaceChildren(
      element("p", "", "Графік недоступний: " + e.message),
    );
  }
}
$("#plan-nav").onclick = () => {
  $("#profile-panel").hidden = true;
  $(".columns").hidden = true;
  $(".filters").hidden = true;
  $("#plan-panel").hidden = false;
  document
    .querySelectorAll(".nav-item")
    .forEach((b) => b.classList.toggle("active", b.id === "plan-nav"));
  renderPlan();
};
$("#auto-toggle").onclick = () => {
  autoUpdate = !autoUpdate;
  $("#auto-toggle").textContent = autoUpdate
    ? `Авто: ${refreshSeconds} с`
    : "Авто: пауза";
  $("#auto-toggle").setAttribute("aria-pressed", String(autoUpdate));
};
function scheduleRefresh() {
  clearTimeout(timer);
  timer = setTimeout(
    async () => {
      if (connected && autoUpdate && !busy) await run(refresh);
      scheduleRefresh();
    },
    refreshSeconds * 1000 * Math.min(4, 2 ** failureCount),
  );
}
scheduleRefresh();

$("#profile-nav").onclick = () => {
  $(".columns").hidden = true;
  $(".filters").hidden = true;
  $("#plan-panel").hidden = true;
  $("#profile-panel").hidden = false;
  document
    .querySelectorAll(".nav-item")
    .forEach((b) => b.classList.toggle("active", b.id === "profile-nav"));
};
$("#jira-form").onsubmit = (event) => {
  event.preventDefault();
  run(async () => {
    let result;
    try {
      result = await api("/api/profile", {
        url: $("#jira-url").value,
        email: $("#jira-email").value,
        token: $("#jira-token").value,
        ...readPreferences(),
      });
    } finally {
      $("#jira-token").value = "";
    }
    applyPreferences(result.profile);
    $("#profile-result").textContent =
      "Профіль збережено на цьому комп’ютері. " +
      (result.jiraConnected
        ? "Токен Jira додано."
        : "Для задач Jira додайте API-токен.");
    if (connected) await refreshPlan();
  });
};

function readPreferences() {
  return {
    timezone: $("#work-zone").value,
    startHour: Number($("#work-start").value),
    endHour: Number($("#work-end").value),
    lunchStart: Number($("#lunch-start").value),
    lunchEnd: Number($("#lunch-end").value),
    weekdays: [...document.querySelectorAll("#workdays input:checked")].map(
      (e) => Number(e.value),
    ),
    refreshSeconds: Number($("#refresh-seconds").value),
    autoAccept: $("#auto-accept").checked,
    teamsClientId: $("#teams-client").value,
  };
}
function applyPreferences(p) {
  for (const [id, key, fallback] of [
    ["work-zone", "timezone", "Europe/Kyiv"],
    ["work-start", "startHour", 9],
    ["work-end", "endHour", 18],
    ["lunch-start", "lunchStart", 13],
    ["lunch-end", "lunchEnd", 14],
    ["refresh-seconds", "refreshSeconds", 30],
    ["teams-client", "teamsClientId", ""],
  ])
    $("#" + id).value = p[key] ?? fallback;
  $("#auto-accept").checked = p.autoAccept ?? true;
  document
    .querySelectorAll("#workdays input")
    .forEach(
      (e) =>
        (e.checked = (p.weekdays || [0, 1, 2, 3, 4]).includes(Number(e.value))),
    );
  refreshSeconds = p.refreshSeconds || 30;
  $("#auto-toggle").textContent = autoUpdate
    ? `Авто: ${refreshSeconds} с`
    : "Авто: пауза";
  $("#automation-status").textContent =
    (p.autoAccept ?? true)
      ? "Автоприйняття увімкнено."
      : "Автоприйняття вимкнено.";
  scheduleRefresh();
}
function showTeamsStatus(status) {
  const target = $("#teams-status");
  target.replaceChildren();
  const descriptions = {
    connected: "Teams підключено. Явні @згадки додаються кандидатами задач.",
    disconnected: "Teams не підключено.",
    error: "Вхід не завершено. Перевірте дозволи організації та повторіть.",
    expired: "Вхід завершився або токен прострочено. Увійдіть повторно.",
  };
  if (status.status === "pending") {
    target.append(
      element(
        "span",
        "",
        "Відкрийте сторінку Microsoft і введіть код: " + status.code + " ",
      ),
    );
    const a = element("a", "", "Відкрити Microsoft ↗");
    const u = new URL(status.url);
    if (
      u.protocol === "https:" &&
      (u.hostname === "microsoft.com" ||
        u.hostname.endsWith(".microsoft.com") ||
        u.hostname === "microsoftonline.com" ||
        u.hostname.endsWith(".microsoftonline.com"))
    ) {
      a.href = u.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      target.append(a);
    }
    setTimeout(async () => {
      try {
        const s = await api("/api/status");
        showTeamsStatus(s.teams);
      } catch {
        target.textContent = "Не вдалося перевірити вхід. Повторіть спробу.";
      }
    }, 5000);
  } else
    target.textContent =
      descriptions[status.status] || descriptions.disconnected;
}
$("#teams-connect").onclick = () =>
  run(async () => {
    const prefs = readPreferences();
    await api("/api/profile", {
      email: $("#jira-email").value,
      url: $("#jira-url").value,
      ...prefs,
    });
    showTeamsStatus(await api("/api/teams/start", {}));
  });
$("#teams-disconnect").onclick = () =>
  run(async () => {
    await api("/api/teams/disconnect", {});
    showTeamsStatus({ status: "disconnected" });
    if (connected) await refreshPlan();
  });

$("#restore-tasks").onclick = () =>
  run(async () => {
    await api("/api/tasks-restore", {});
    await refreshPlan();
  });
