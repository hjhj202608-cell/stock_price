const OWNER = "hjhj202608-cell";
const REPO = "stock_price";
const WATCHLIST_PATH = "watchlist.json";
const MAX_SECURITIES = 10;

function normalizeName(value) {
  return String(value).replace(/\s+/g, "").toLocaleLowerCase("ko-KR");
}

function decodeBase64Utf8(value) {
  const bytes = Uint8Array.from(atob(value.replace(/\n/g, "")), (char) =>
    char.charCodeAt(0),
  );
  return new TextDecoder().decode(bytes);
}

function encodeBase64Utf8(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function githubRequest(env, path, options = {}) {
  const response = await fetch(`https://api.github.com${path}`, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "stock-price-telegram-webhook",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub API ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

async function loadWatchlist(env) {
  const file = await githubRequest(
    env,
    `/repos/${OWNER}/${REPO}/contents/${WATCHLIST_PATH}?ref=main`,
  );
  return {
    sha: file.sha,
    watchlist: JSON.parse(decodeBase64Utf8(file.content)),
  };
}

async function saveWatchlist(env, sha, watchlist) {
  const content = `${JSON.stringify(watchlist, null, 2)}\n`;
  await githubRequest(env, `/repos/${OWNER}/${REPO}/contents/${WATCHLIST_PATH}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "Update Telegram bot watchlist",
      content: encodeBase64Utf8(content),
      sha,
      branch: "main",
      committer: {
        name: "stock-price-bot",
        email: "stock-price-bot@users.noreply.github.com",
      },
    }),
  });
}

async function searchSecurities(query) {
  const url = new URL("https://ac.stock.naver.com/ac");
  url.searchParams.set("q", query);
  url.searchParams.set("target", "stock");
  const response = await fetch(url, {
    headers: { "User-Agent": "stock-price-telegram-webhook/1.0" },
  });
  if (!response.ok) throw new Error(`Security search ${response.status}`);
  const payload = await response.json();
  return (payload.items || [])
    .map((item) => ({
      code: String(item.code || "").trim().toUpperCase(),
      name: String(item.name || "").trim(),
      nationCode: item.nationCode,
      category: item.category,
    }))
    .filter(
      (item) =>
        item.nationCode === "KOR" &&
        item.category === "stock" &&
        /^[0-9A-Z]{6}$/.test(item.code) &&
        item.name,
    );
}

function helpMessage() {
  return [
    "종가 알림 종목 관리 방법",
    "• 추가 삼성전자",
    "• 삭제 삼성전자",
    "• 목록",
    "",
    "종목명만 보내면 코드를 확인해 즉시 처리합니다.",
  ].join("\n");
}

async function processCommand(env, input) {
  const text = input.trim().replace(/^\//, "");
  const firstSpace = text.search(/\s/);
  const command = (firstSpace < 0 ? text : text.slice(0, firstSpace))
    .split("@")[0]
    .toLocaleLowerCase("ko-KR");
  const argument = firstSpace < 0 ? "" : text.slice(firstSpace).trim();

  if (["도움말", "도움", "help", "start"].includes(command)) {
    return helpMessage();
  }

  if (["목록", "list"].includes(command)) {
    const { watchlist } = await loadWatchlist(env);
    if (!watchlist.length) return "현재 등록된 종목이 없습니다.";
    return [
      "현재 종가 알림 종목",
      ...watchlist.map((item) => `• ${item.name} (${item.code})`),
    ].join("\n");
  }

  if (["추가", "add"].includes(command)) {
    if (!argument) return "형식: 추가 삼성전자";

    let code;
    let name;
    const legacy = argument.match(/^([0-9A-Z]{6})\s+(.+)$/i);
    if (legacy) {
      code = legacy[1].toUpperCase();
      name = legacy[2].trim();
    } else {
      const candidates = await searchSecurities(argument);
      const exact = candidates.filter(
        (item) => normalizeName(item.name) === normalizeName(argument),
      );
      if (exact.length !== 1) {
        if (!candidates.length) {
          return `국내 상장 종목을 찾지 못했습니다: ${argument}`;
        }
        return [
          `정확히 일치하는 종목이 없습니다: ${argument}`,
          "아래 이름 중 하나를 그대로 보내 주세요.",
          ...candidates.slice(0, 5).map((item) => `• 추가 ${item.name}`),
        ].join("\n");
      }
      ({ code, name } = exact[0]);
    }

    const { sha, watchlist } = await loadWatchlist(env);
    const existing = watchlist.find((item) => item.code === code);
    if (existing) {
      if (existing.name === name) {
        return `이미 등록된 종목입니다: ${name} (${code})`;
      }
      existing.name = name;
      await saveWatchlist(env, sha, watchlist);
      return `종목명을 변경했습니다: ${name} (${code})`;
    }
    if (watchlist.length >= MAX_SECURITIES) {
      return `종목은 최대 ${MAX_SECURITIES}개까지 등록할 수 있습니다.`;
    }
    watchlist.push({ code, name });
    await saveWatchlist(env, sha, watchlist);
    return `추가했습니다: ${name} (${code})`;
  }

  if (["삭제", "제거", "remove", "delete"].includes(command)) {
    if (!argument) return "형식: 삭제 삼성전자";
    const { sha, watchlist } = await loadWatchlist(env);
    const matches = /^[0-9A-Z]{6}$/i.test(argument)
      ? watchlist.filter((item) => item.code === argument.toUpperCase())
      : watchlist.filter(
          (item) => normalizeName(item.name) === normalizeName(argument),
        );
    if (matches.length > 1) {
      return [
        "같은 이름의 종목이 여러 개입니다. 종목코드로 삭제해 주세요.",
        ...matches.map((item) => `• 삭제 ${item.code} (${item.name})`),
      ].join("\n");
    }
    if (!matches.length) return `등록되지 않은 종목입니다: ${argument}`;
    const existing = matches[0];
    await saveWatchlist(
      env,
      sha,
      watchlist.filter((item) => item.code !== existing.code),
    );
    return `삭제했습니다: ${existing.name} (${existing.code})`;
  }

  return helpMessage();
}

async function sendTelegram(env, chatId, text) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    },
  );
  if (!response.ok) throw new Error(`Telegram API ${response.status}`);
}

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return new Response("stock-price Telegram webhook is ready");
    }
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }
    if (
      request.headers.get("X-Telegram-Bot-Api-Secret-Token") !==
      env.WEBHOOK_SECRET
    ) {
      return new Response("Forbidden", { status: 403 });
    }

    const update = await request.json();
    const message = update.message || update.edited_message || {};
    const chatId = String((message.chat || {}).id || "");
    if (chatId !== String(env.TELEGRAM_CHAT_ID) || typeof message.text !== "string") {
      return new Response("OK");
    }

    try {
      const reply = await processCommand(env, message.text);
      await sendTelegram(env, chatId, reply);
    } catch (error) {
      console.error(error);
      await sendTelegram(
        env,
        chatId,
        "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
      );
    }
    return new Response("OK");
  },
};
