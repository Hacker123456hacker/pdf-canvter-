/**
 * Bhakti Telegram webhook controller.
 * Required Worker secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
 * GITHUB_TOKEN (fine-grained PAT with Actions read/write), WEBHOOK_SECRET.
 */
const OWNER = "Hacker123456hacker";
const REPO = "pdf-canvter-";
const WORKFLOW = "auto-youtube.yml";
const API = "https://api.github.com";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function constantTimeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function telegram(env, method, payload) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(`Telegram ${method} failed: ${data.description || response.status}`);
  return data.result;
}

async function github(env, path, method = "GET", body) {
  const response = await fetch(API + path, {
    method,
    headers: {
      "authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "accept": "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "Bhakti-Telegram-Webhook",
      ...(body ? { "content-type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (response.status === 204) return {};
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`GitHub API ${response.status}: ${data.message || "request failed"}`);
  return data;
}

async function send(env, text) {
  await telegram(env, "sendMessage", {
    chat_id: env.TELEGRAM_CHAT_ID,
    text: String(text).slice(0, 3900),
    disable_web_page_preview: true,
  });
}

async function status(env) {
  const data = await github(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=5`);
  const runs = data.workflow_runs || [];
  if (!runs.length) return "अभी तक कोई video workflow run नहीं मिला।";
  const r = runs[0];
  return [
    "📊 Latest run status",
    `Status: ${r.status || "unknown"}`,
    `Result: ${r.conclusion || "running/not finished"}`,
    `Run: #${r.run_number}`,
    `Started: ${r.run_started_at || r.created_at || "unknown"}`,
    `Details: ${r.html_url}`,
  ].join("\n");
}

async function lastVideo(env) {
  const data = await github(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=20`);
  const runs = data.workflow_runs || [];
  const r = runs.find(x => x.conclusion === "success");
  if (!r) return "अभी कोई successful video workflow run नहीं मिला।";
  return [
    "🎬 Latest successful video run",
    `Run: #${r.run_number}`,
    `Started: ${r.run_started_at || r.created_at || "unknown"}`,
    "YouTube URL पाने के लिए अभी success notification देखें; run metadata में link उपलब्ध नहीं है।",
    `Run/artifact: ${r.html_url}`,
  ].join("\n");
}

async function handleUpdate(env, update) {
  const message = update.message;
  if (!message || !message.text) return;
  const chatId = String(message.chat?.id ?? "");
  if (chatId !== String(env.TELEGRAM_CHAT_ID)) return;
  const command = message.text.trim().split(/\s+/)[0].toLowerCase().split("@")[0];
  const help = [
    "🤖 Bhakti YouTube Control",
    "/status — latest run status",
    "/run — start a Bhakti video now",
    "/pause — pause scheduled/manual video workflow",
    "/resume — resume workflow and schedule",
    "/lastvideo — latest successful run/artifact",
    "/help — show commands",
    "",
    "Commands are accepted only from your configured Telegram chat.",
  ].join("\n");

  try {
    if (command === "/start" || command === "/help") {
      await send(env, help);
    } else if (command === "/status") {
      await send(env, await status(env));
    } else if (command === "/lastvideo") {
      await send(env, await lastVideo(env));
    } else if (command === "/run") {
      await github(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, "POST", {
        ref: "main",
        inputs: { video_type: "bhakti" },
      });
      await send(env, "🚀 Bhakti video workflow start request GitHub को भेज दी गई है। थोड़ी देर में /status से देख सकते हैं।");
    } else if (command === "/pause") {
      await github(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/disable`, "PUT");
      await send(env, "⏸️ Video workflow pause कर दिया गया है। /resume से फिर चालू करें।");
    } else if (command === "/resume") {
      await github(env, `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/enable`, "PUT");
      await send(env, "▶️ Video workflow resume कर दिया गया है।");
    } else {
      await send(env, "यह command उपलब्ध नहीं है। /help भेजें।");
    }
  } catch (error) {
    // Keep secrets out of Telegram and logs.
    console.error("Telegram command failed", { command, error: String(error).slice(0, 300) });
    await send(env, "❌ Command execute नहीं हुआ। GitHub token permissions और Actions status जाँचें।");
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") return json({ ok: true, service: "Bhakti Telegram webhook" });
    if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

    const supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!env.WEBHOOK_SECRET || !constantTimeEqual(supplied, env.WEBHOOK_SECRET)) {
      return json({ error: "Unauthorized" }, 401);
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return json({ error: "Invalid JSON" }, 400);
    }

    // Telegram receives an immediate acknowledgement; command work continues safely.
    ctx.waitUntil(handleUpdate(env, update));
    return json({ ok: true });
  },
};
