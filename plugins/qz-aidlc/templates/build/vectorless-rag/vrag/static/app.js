const log = document.getElementById("log");
const who = document.getElementById("as");

function add(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  log.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "end" });
  return div;
}

fetch("/api/users").then(r => r.json()).then(d => {
  for (const u of d.users) {
    const o = document.createElement("option");
    o.value = o.textContent = u;
    who.appendChild(o);
  }
});

document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = document.getElementById("q");
  const question = box.value.trim();
  if (!question) return;
  box.value = "";
  add("q", question);
  const out = add("", "…");
  try {
    const r = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, as: who.value }),
    });
    const a = await r.json();
    if (!r.ok) { out.textContent = a.error || "Something went wrong."; return; }
    out.textContent = a.text;
    if (a.refused) out.classList.add("refused");
    if (a.citations && a.citations.length) {
      const ul = document.createElement("ul");
      ul.className = "cites";
      for (const c of a.citations) {
        const li = document.createElement("li");
        li.textContent = `[${c.n}] ${c.doc_title} › ${c.section}` + (c.page ? `, page ${c.page}` : "");
        ul.appendChild(li);
      }
      out.appendChild(ul);
    }
    if (a.redactions) {
      const n = document.createElement("div");
      n.className = "note";
      n.textContent = "Personal data was removed from this answer.";
      out.appendChild(n);
    }
    if ((a.flags || []).includes("answered from the cache")) {
      const n = document.createElement("div");
      n.className = "note";
      n.textContent = "Answered from the cache: the same question was asked before, so no search or model call was needed.";
      out.appendChild(n);
    }
  } catch (err) {
    out.textContent = "The assistant could not be reached.";
  }
});
