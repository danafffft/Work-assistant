let workspace = { tasks: [], rules: [], journal: [], meetings: [] };
async function hubAction(body) {
  await api("/api/workspace", body);
  if (connected) await refreshPlan();
  await loadHub();
}
function actionButton(label, body) {
  const b = element("button", "", label);
  b.onclick = () => run(() => hubAction(body));
  return b;
}
async function loadHub() {
  workspace = await api("/api/workspace");
  renderHub();
}
function renderHub() {
  const now = new Date(),
    active = workspace.tasks.filter((t) => t.status === "active");
  const upcoming = workspace.meetings
    .filter((m) => new Date(m.end) > now && !m.pinnedTask)
    .sort((a, b) => new Date(a.start) - new Date(b.start));
  const summary = $("#day-summary");
  summary.replaceChildren(
    element(
      "p",
      "",
      `Активних: ${active.length} · Потребують підтвердження: ${workspace.tasks.filter((t) => t.status === "candidate").length}`,
    ),
  );
  summary.append(
    element(
      "p",
      "",
      `Потрібно відповісти: ${active.filter((t) => t.source === "Лист · відповісти").length} · Очікуєте відповідь: ${active.filter((t) => t.source === "Лист · очікування").length}`,
    ),
  );
  const top = [...active]
    .sort(
      (a, b) =>
        (a.due || "9999").localeCompare(b.due || "9999") ||
        (a.rank || 3) - (b.rank || 3),
    )
    .slice(0, 3);
  for (const t of top)
    summary.append(
      element("p", "", `→ ${t.title}${t.due ? " · до " + t.due : ""}`),
    );
  if (upcoming[0]) {
    const meeting = upcoming[0],
      c = element("article", "card");
    c.append(
      element("h3", "subject", "Найближча нарада: " + meeting.title),
      element("p", "", new Date(meeting.start).toLocaleString("uk-UA")),
    );
    const b = element("button", "", "Підготуватися");
    b.onclick = () => {
      const words = (
        meeting.title.toLowerCase().match(/[\p{L}\d-]{4,}/gu) || []
      ).filter(
        (w) => !["meeting", "нарада", "зустріч", "call", "teams"].includes(w),
      );
      const matches = [
        ...messages.map((m) => ({
          title: m.subject,
          text: m.bodyPreview || "",
        })),
        ...active.map((t) => ({ title: t.title, text: "" })),
      ].filter((i) =>
        words.some((w) => (i.title + " " + i.text).toLowerCase().includes(w)),
      );
      c.append(
        element(
          "p",
          "",
          "Пов’язані матеріали за словами в назві (перевірте відповідність):",
        ),
      );
      for (const m of matches.slice(0, 10)) c.append(element("p", "", m.title));
      if (!matches.length)
        c.append(
          element("p", "", "Збігів серед завантажених листів і задач немає."),
        );
      b.disabled = true;
    };
    c.append(b);
    summary.append(c);
  }
  const list = $("#hub-tasks");
  list.replaceChildren();
  const filter = $("#task-filter").value;
  for (const t of workspace.tasks.filter((t) => t.status === filter)) {
    const card = element("article", "card");
    card.draggable = true;
    card.ondragstart = (e) => e.dataTransfer.setData("text/plain", t.id);
    card.append(
      element("h3", "subject", t.title),
      element(
        "p",
        "",
        `${t.source} · ${t.minutes} хв${t.due ? " · до " + t.due : ""}${t.pin ? " · закріплено" : ""}`,
      ),
    );
    if (t.due && new Date(t.due + "T23:59:59") < now)
      card.append(element("span", "tag high", "Прострочено"));
    if (t.status === "candidate")
      card.append(
        actionButton("Прийняти задачу", {
          action: "status",
          id: t.id,
          status: "active",
        }),
      );
    if (t.status === "active")
      card.append(
        actionButton("Виконано", {
          action: "status",
          id: t.id,
          status: "done",
        }),
      );
    if (t.status !== "dismissed")
      card.append(
        actionButton("Відхилити", {
          action: "status",
          id: t.id,
          status: "dismissed",
        }),
      );
    if (t.status === "done" || t.status === "dismissed")
      card.append(
        actionButton("Повернути", {
          action: "status",
          id: t.id,
          status: "active",
        }),
      );
    if (t.pin)
      card.append(
        actionButton("Відкріпити", { action: "pin", id: t.id, start: null }),
      );
    list.append(card);
  }
  if (!list.childNodes.length)
    list.append(element("p", "", "У цьому списку поки порожньо."));
  $("#pin-task").replaceChildren(
    ...active
      .filter((t) => t.source !== "Лист · очікування")
      .map((t) => {
        const o = element("option", "", t.title);
        o.value = t.id;
        return o;
      }),
  );
  $("#hub-rules").replaceChildren(
    ...workspace.rules
      .filter((r) => r.enabled)
      .map((r) => {
        const c = element("p", "", r.sender + " → " + r.category);
        c.append(
          actionButton("Вимкнути", { action: "rule-disable", id: r.id }),
        );
        return c;
      }),
  );
  $("#hub-journal").replaceChildren(
    ...workspace.journal.map((e) => {
      const c = element("div", "card");
      c.append(
        element(
          "p",
          "",
          new Date(e.at).toLocaleString("uk-UA") +
            " · " +
            (e.kind === "task"
              ? "Доручення"
              : e.kind === "external"
                ? "Outlook"
                : "Правило") +
            " · " +
            (e.after.title || e.after.sender),
        ),
      );
      if (!e.undone && e.kind !== "external")
        c.append(actionButton("Скасувати", { action: "undo", id: e.id }));
      else
        c.append(
          element(
            "span",
            "tag",
            e.kind === "external" ? e.after.outcome : "Скасовано",
          ),
        );
      return c;
    }),
  );
}
$("#day-nav").onclick = () => {
  showMail();
  $(".columns").hidden = true;
  $(".filters").hidden = true;
  $("#hub-panel").hidden = false;
  document
    .querySelectorAll(".nav-item")
    .forEach((b) => b.classList.toggle("active", b.id === "day-nav"));
  run(async () => {
    if (connected) await refreshPlan();
    await loadHub();
  });
};
$("#task-filter").onchange = renderHub;
$("#task-form").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    await hubAction({
      action: "task",
      title: $("#task-title").value,
      minutes: Number($("#task-minutes").value),
      due: $("#task-due").value,
    });
    $("#task-title").value = "";
  });
};
$("#pin-form").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    if (!connected)
      throw Error("Спочатку підключіть Outlook, щоб перевірити конфлікти.");
    await api("/api/plan");
    await hubAction({
      action: "pin",
      id: $("#pin-task").value,
      start: new Date($("#pin-start").value).toISOString(),
    });
  });
};
$("#pin-drop").ondragover = (e) => e.preventDefault();
$("#pin-drop").ondrop = (e) => {
  e.preventDefault();
  const id = e.dataTransfer.getData("text/plain");
  if (workspace.tasks.some((t) => t.id === id && t.status === "active")) {
    $("#pin-task").value = id;
    $("#pin-start").focus();
  }
};

$("#check-updates").onclick = () =>
  run(async () => {
    const data = await api("/api/update");
    const target = $("#update-result");
    target.replaceChildren(
      element(
        "span",
        "",
        data.latest
          ? `Встановлено ${data.current}. Останній реліз: ${data.latest}. `
          : data.message + " ",
      ),
    );
    const a = element("a", "", "Відкрити сторінку оновлення ↗");
    a.href = data.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    target.append(a);
  });
