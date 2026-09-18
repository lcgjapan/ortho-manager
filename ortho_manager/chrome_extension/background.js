const MARKER = "om_reuse";
const STORAGE_KEY = "orthoManagerGoogleMapsTabId";

function cleanRequestUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.searchParams.get(MARKER) !== "1") {
    return null;
  }
  url.searchParams.delete(MARKER);
  return url.toString();
}

async function storedTabId() {
  const values = await chrome.storage.local.get(STORAGE_KEY);
  return values[STORAGE_KEY];
}

async function rememberTab(tabId) {
  await chrome.storage.local.set({ [STORAGE_KEY]: tabId });
}

chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
  if (details.frameId !== 0) return;
  const cleanUrl = cleanRequestUrl(details.url);
  if (!cleanUrl) return;

  const targetId = await storedTabId();
  if (Number.isInteger(targetId) && targetId !== details.tabId) {
    try {
      const target = await chrome.tabs.get(targetId);
      await chrome.tabs.update(targetId, { url: cleanUrl, active: true });
      await chrome.windows.update(target.windowId, { focused: true });
      await chrome.tabs.remove(details.tabId);
      return;
    } catch (_error) {
      await chrome.storage.local.remove(STORAGE_KEY);
    }
  }

  await rememberTab(details.tabId);
  await chrome.tabs.update(details.tabId, { url: cleanUrl, active: true });
}, { url: [{ hostEquals: "www.google.com", pathPrefix: "/maps" }] });

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (tabId === await storedTabId()) {
    await chrome.storage.local.remove(STORAGE_KEY);
  }
});
