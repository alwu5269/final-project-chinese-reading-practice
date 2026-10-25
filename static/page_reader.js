// Injected by desktop.py into the browser pane: lets you read aloud directly on the web page.
// Wraps the page's Chinese text into clickable passages and colors characters after scoring.
// Talks to the desktop app through console messages prefixed "MAOMAO:".
(() => {
  if (window.__mm) return;
  const HAN = /[\u4e00-\u9fff]/;
  const SKIP = "script,style,noscript,nav,header,footer,aside,sup,button,select,textarea,input,figcaption,[role=navigation],[role=dialog]," +
    ".mw-editsection,.reference,.ambox,.hatnote,.navbox,.infobox,.metadata,.toc,.thumb,.catlinks,.mw-references-wrap";
  // Main article area if the site marks one; otherwise the whole page
  const ROOT_SEL = "#mw-content-text, article, main, [role=main], .article-content, .post-content, .entry-content, #content";
  const SENT_END = /[。！？!?]/;
  const send = msg => console.log("MAOMAO:" + JSON.stringify(msg));
  let units = [], active = -1, on = false, lang = "zh", script = "", converted = "";
  let pick = null, pickMarkers = null;  // a highlighted selection being read instead of a paragraph
  const current = () => pick || units[active];
  const EN_WORD = /\d+\/\d+|[½⅓¼¾⅔]|\d+(?:[.,]\d+)*%?°?|&|[A-Za-z]+(?:['’.][A-Za-z]+)*/g;  // same as EN_TOKEN in scoring.py
  const scored = s => lang === "en" ? true : HAN.test(s.textContent);  // which spans line up with scoring results
  const count = text => lang === "en" ? (text.match(EN_WORD) || []).length : (text.match(/[\u4e00-\u9fff]/g) || []).length;

  const css = document.createElement("style");
  css.textContent = `
    .mm-on .mm-unit { cursor: pointer; }
    .mm-on .mm-unit:hover { background: rgba(232,130,58,.10); }
    .mm-active { background: rgba(253,233,214,.95) !important; box-shadow: 0 0 0 3px rgba(253,233,214,.95); border-radius: 4px; }
    .mm-tone { background: #fff0c9 !important; color: #a86a00 !important; border-radius: 3px; }
    .mm-misread { background: #fde1e6 !important; color: #c8384f !important; border-radius: 3px; }
    .mm-skipped { background: #eee6dc !important; color: #8b7b70 !important; text-decoration: line-through; }
    .mm-unread { opacity: .45; }
    .mm-pause { box-shadow: inset 3px 0 0 #e8823a; padding-left: 3px; }
    .mm-c[data-tip]:hover::after { content: attr(data-tip); position: absolute; transform: translate(-50%, -130%); background: #3d2f28; color: #fff;
      font-size: 12px; padding: 3px 8px; border-radius: 8px; white-space: nowrap; pointer-events: none; z-index: 99999; }
    .mm-c { position: relative; }
    .mm-c[data-py]::before { content: attr(data-py); position: absolute; left: 50%; transform: translateX(-50%); top: -1.15em;
      font-size: 10px; letter-spacing: -.2px; line-height: 1; white-space: nowrap; color: #c4651f; font-family: -apple-system, sans-serif; font-style: normal; font-weight: 400;
      visibility: hidden; pointer-events: none; }
    /* Shown pinyin sits in the flow (character box widens to fit it), so neighbours never overlap */
    .mm-py-on .mm-active[data-py], .mm-tone[data-py], .mm-misread[data-py] {
      display: inline-flex; flex-direction: column; align-items: center; vertical-align: bottom; line-height: 1.3; padding: 6px 1px 0; }
    .mm-py-on .mm-active[data-py]::before, .mm-tone[data-py]::before, .mm-misread[data-py]::before {
      position: static; transform: none; visibility: visible; margin-bottom: 1px; }
    .mm-roomy { line-height: 2.1 !important; }`;
  document.head.appendChild(css);

  function blocks() {
    const root = document.querySelector(ROOT_SEL) || document.body;
    const all = [...root.querySelectorAll("p, li, dd, blockquote, h1, h2, h3, td, div")];
    return all.filter(el => {
      if (el.closest(SKIP) || !el.offsetParent) return false;
      // keep the innermost element that holds the text itself
      const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("");
      if (el.tagName === "DIV" || el.tagName === "TD") return count(own) >= 12;
      return count(el.textContent) >= (lang === "en" ? 8 : 6);
    }).filter((el, _, arr) => !arr.some(o => o !== el && el.contains(o) && o.tagName !== "DIV"));
  }

  function wrap(block) {
    // Wrap each visible character into a span, leaving links and formatting in place
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, {
      acceptNode: n => n.parentElement.closest(SKIP) || n.parentElement.closest(".mm-c") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    return wrapNodes(nodes);
  }

  function wrapNodes(nodes) {
    const spans = [];
    // Only Chinese characters and CJK punctuation get spans; Latin words and numbers stay plain text
    const CJK = /[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]/;
    if (lang === "en") {  // English: one span per word
      for (const node of nodes) {
        const text = node.textContent;
        EN_WORD.lastIndex = 0; if (!EN_WORD.test(text)) continue;
        EN_WORD.lastIndex = 0;
        const frag = document.createDocumentFragment(); let last = 0, m;
        while ((m = EN_WORD.exec(text))) {
          if (m.index > last) frag.append(text.slice(last, m.index));
          const s = document.createElement("span"); s.className = "mm-c"; s.textContent = m[0];
          frag.append(s); spans.push(s); last = m.index + m[0].length;
        }
        if (last < text.length) frag.append(text.slice(last));
        node.replaceWith(frag);
      }
      return spans;
    }
    for (const node of nodes) {
      if (!CJK.test(node.textContent)) continue;
      const frag = document.createDocumentFragment();
      let run = "";
      for (const ch of node.textContent) {
        if (!CJK.test(ch)) { run += ch; continue; }
        if (run) { frag.append(run); run = ""; }
        const s = document.createElement("span"); s.className = "mm-c"; s.textContent = ch;
        frag.append(s); spans.push(s);
      }
      if (run) frag.append(run);
      node.replaceWith(frag);
    }
    return spans;
  }

  function split(spans) {
    // One passage per paragraph; long paragraphs split at sentence ends (~180 characters)
    const out = []; let cur = [];
    spans.forEach((s, i) => {
      cur.push(s);
      if (lang === "en") {  // sentence ends sit in the text right after the word
        const after = s.nextSibling && s.nextSibling.nodeType === 3 ? s.nextSibling.textContent : "";
        if ((/^[)"”’]?[.!?]/.test(after) && cur.length >= 40) || cur.length >= 70) { out.push(cur); cur = []; }
        return;
      }
      const end = SENT_END.test(s.textContent) && !SENT_END.test(spans[i + 1]?.textContent || "");
      if ((end && cur.length >= 180) || cur.length >= 300) { out.push(cur); cur = []; }
    });
    if (cur.filter(scored).length >= 2) out.push(cur);
    return out;
  }

  // Simplified/traditional: every Chinese text node on the page (title, headings, body) is converted
  // in place, node by node, so a conversion that changes a node's length can't break the rest
  let pending = [];
  function convert(toScript) {
    if (!toScript || converted === toScript) return false;
    const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT, {
      acceptNode: n => HAN.test(n.nodeValue) && !n.parentElement.closest("script,style,noscript,textarea") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    pending = []; while (walker.nextNode()) pending.push(walker.currentNode);
    if (!pending.length) { converted = toScript; return false; }
    send({ type: "convert", script: toScript, texts: pending.map(n => n.nodeValue) });
    return true;
  }
  // Called back with the converted text of each node
  function applyTexts(texts, toScript) {
    if (!pending.length) return;  // a reply to a request that was already answered
    pending.forEach((n, i) => { if (typeof texts[i] === "string" && texts[i] !== n.nodeValue) n.nodeValue = texts[i]; });
    pending = []; converted = toScript;
    if (on) start(lang, script);
  }

  function start(language, wantScript) {
    if (language && language !== lang) { lang = language; units = []; active = -1; }
    script = wantScript || "";
    on = true;
    if (lang === "zh" && convert(script)) return;  // convert the page first; applyTexts() comes back here
    if (!units.length) {
      for (const b of blocks()) for (const u of split(wrap(b))) units.push(u);
      units.forEach((u, i) => u.forEach(s => { s.classList.add("mm-unit"); s.dataset.unit = i; }));
    }
    on = true; document.documentElement.classList.add("mm-on");
    if (pickMarkers) return readPick();
    if (pick) return;  // keep reading the highlighted selection
    if (!units.length) return send({ type: "error", message: `Mao couldn't find ${lang === "en" ? "English" : "Chinese"} article text on this page.` });
    select(active >= 0 ? active : 0);
  }

  function stop() { on = false; document.documentElement.classList.remove("mm-on"); }

  function select(i) {
    if (i < 0 || i >= units.length) return;
    if (pick) { pick.forEach(s => s.classList.remove("mm-active")); pick = null; }
    if (active >= 0) units[active].forEach(s => s.classList.remove("mm-active"));
    active = i;
    units[i].forEach(s => s.classList.add("mm-active"));
    units[i][0].scrollIntoView({ behavior: "smooth", block: "center" });
    const range = document.createRange();  // includes the plain-text Latin words and numbers between spans
    range.setStartBefore(units[i][0]); range.setEndAfter(units[i][units[i].length - 1]);
    const text = range.toString().replace(/\[\d+\]/g, "").replace(/\s+/g, " ").trim();
    send({ type: "passage", text, index: i, total: units.length, title: document.title, url: location.href });
  }

  function clearMarks(u) {
    u.forEach(s => { s.classList.remove("mm-tone", "mm-misread", "mm-skipped", "mm-unread", "mm-pause"); delete s.dataset.tip; });
  }

  function setPinyin(list, show) {
    if (!current()) return;
    if (list) {
      let k = 0;
      for (const s of current()) if (scored(s)) s.dataset.py = list[k++] || "";
    }
    document.documentElement.classList.toggle("mm-py-on", !!show);
    // make room above the lines for pinyin
    const blocks = new Set(current().map(s => s.parentElement.closest("p, li, dd, blockquote, h1, h2, h3, td, div")));
    blocks.forEach(b => b && b.classList.toggle("mm-roomy", !!show || !!current().some(s => s.classList.contains("mm-tone") || s.classList.contains("mm-misread"))));
  }

  function mark(results) {
    if (!current()) return;
    const u = current(); clearMarks(u);
    let k = 0;
    for (const s of u) {
      if (!scored(s)) continue;
      const r = results[k++]; if (!r) break;
      if (["tone", "misread", "skipped", "unread"].includes(r.status)) s.classList.add("mm-" + r.status);
      if (r.status === "tone" || r.status === "misread") s.dataset.tip = r.heard_pinyin ? `Mao heard ${r.heard} (${r.heard_pinyin})` : `Mao heard “${r.heard}”`;
      if (r.status === "skipped") s.dataset.tip = "Skipped";
      if (r.tone_from_pitch) s.dataset.tip = `Tone slip: your voice was ${r.you_shape}, native is ${r.native_shape}`;
      if (r.pause) { s.classList.add("mm-pause"); s.dataset.tip = (s.dataset.tip ? s.dataset.tip + " · " : "") + `paused ${r.pause}s`; }
    }
    setPinyin(null, document.documentElement.classList.contains("mm-py-on"));
  }

  // Clicking a passage selects it (links are not followed while reading mode is on)
  document.addEventListener("click", e => {
    if (!on) return;
    const s = e.target.closest(".mm-unit, .mm-c"); if (!s) return;
    const inCurrent = current() && current().includes(s);
    if (!inCurrent && !s.classList.contains("mm-unit")) return;
    e.preventDefault(); e.stopPropagation();
    if (!inCurrent) return select(+s.dataset.unit);
    // In the passage you're reading: look up the tapped character (with a few neighbours for context)
    const han = current().filter(scored), k = han.indexOf(s);
    if (k < 0 || lang === "en") return;
    const from = Math.max(0, k - 3);
    send({ type: "define", text: han.slice(from, k + 4).map(x => x.textContent).join(""), index: k - from });
  }, true);

  // ---------- Highlight any text, then "Read this" ----------
  const readBtn = document.createElement("button");
  readBtn.textContent = "🐾 Read this";
  readBtn.style.cssText = "position:absolute;z-index:2147483647;display:none;padding:6px 12px;border:0;border-radius:999px;" +
    "background:#e8823a;color:#fff;font:600 13px -apple-system,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.25);cursor:pointer";
  document.body.appendChild(readBtn);
  readBtn.addEventListener("mousedown", e => e.preventDefault());  // keep the selection
  const enoughText = t => count(t) >= 2;

  document.addEventListener("mouseup", e => {
    if (e.target === readBtn) return;
    setTimeout(() => {
      const sel = getSelection();
      if (!sel.rangeCount || sel.isCollapsed || !enoughText(sel.toString())) { readBtn.style.display = "none"; return; }
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      readBtn.style.left = `${rect.left + scrollX}px`; readBtn.style.top = `${rect.bottom + scrollY + 6}px`;
      readBtn.style.display = "block";
    }, 0);
  });

  readBtn.addEventListener("click", e => {
    e.preventDefault(); e.stopPropagation(); readBtn.style.display = "none";
    const sel = getSelection(); if (!sel.rangeCount) return;
    // Two empty markers keep the selection's place while the page's text is wrapped or converted
    const range = sel.getRangeAt(0), a = document.createElement("i"), b = document.createElement("i");
    const end = range.cloneRange(); end.collapse(false); end.insertNode(b);
    const startR = range.cloneRange(); startR.collapse(true); startR.insertNode(a);
    sel.removeAllRanges();
    pickMarkers = [a, b];
    if (on) return readPick();
    send({ type: "reading", on: true });
    start(lang, script);
  });

  function readPick() {
    const [a, b] = pickMarkers; pickMarkers = null;
    const range = document.createRange(); range.setStartAfter(a); range.setEndBefore(b);
    const root = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: n => range.intersectsNode(n) && !n.parentElement.closest("script,style,noscript") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    const spans = [];
    for (const n of nodes) {
      const wrapped = n.parentElement.closest(".mm-c");
      if (wrapped) { if (!spans.includes(wrapped)) spans.push(wrapped); }
      else spans.push(...wrapNodes([n]));
    }
    a.remove(); b.remove();
    if (spans.filter(scored).length < 2) return;
    if (pick) pick.forEach(s => s.classList.remove("mm-active"));
    if (active >= 0) units[active].forEach(s => s.classList.remove("mm-active"));
    pick = spans;
    spans.forEach(s => s.classList.add("mm-active"));
    const r = document.createRange(); r.setStartBefore(spans[0]); r.setEndAfter(spans[spans.length - 1]);
    const text = r.toString().replace(/\[\d+\]/g, "").replace(/\s+/g, " ").trim();
    send({ type: "passage", text, index: Math.max(active, 0), total: units.length || 1, title: "Your selection · " + document.title, url: location.href });
  }

  // Called on every page load: remember the language and character set, and convert the page now
  function prime(language, wantScript) {
    if (!on) { if (language !== lang) units = []; lang = language; script = wantScript || ""; }
    if (lang === "zh") convert(wantScript);
  }

  window.__mm = { prime, convert, applyTexts, start, stop, select, setPinyin, next: () => select(active + 1), prev: () => select(active - 1), mark };
})();
