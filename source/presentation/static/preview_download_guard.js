(() => {
  if (window.__previewDownloadGuardInjected) {
    return;
  }
  window.__previewDownloadGuardInjected = true;

  const FILE_RE = /\.(pdf|hwp|hwpx|zip|rar|7z|doc|docx|xls|xlsx|ppt|pptx|csv)(\?|#|$)/i;
  const DOWNLOAD_PATH_RE =
    /(?:\/(?:cmm\/fms\/)?filedown\.do|\/download(?:\/|$)|\/file\/download(?:\/|$)|\/fms\/filedown\.do)/i;
  const DOWNLOAD_QUERY_RE = /(?:[?&](?:atchfileid|filesn|fileid|download|attachment|attach)=)/i;

  const normalizeUrl = (href) => {
    try {
      return new URL(href, window.location.href).toString();
    } catch (_) {
      return href;
    }
  };

  const hasFileHint = (anchor) => {
    if (!anchor) return false;
    const text = (anchor.textContent || "").toLowerCase();
    if (/\.(pdf|hwp|hwpx|zip|rar|7z|doc|docx|xls|xlsx|ppt|pptx|csv)\b/.test(text)) {
      return true;
    }
    const img = anchor.querySelector ? anchor.querySelector("img") : null;
    const alt = (img && img.alt ? img.alt : "").toLowerCase();
    return /\uCCA8\uBD80\uD30C\uC77C|file/i.test(alt);
  };

  const shouldOpenExternal = (anchor) => {
    if (!anchor) return false;
    if (anchor.hasAttribute("download")) return true;

    const href = anchor.getAttribute("href") || "";
    if (!href) return false;

    const onClick = (anchor.getAttribute("onclick") || "").toLowerCase();
    if (DOWNLOAD_PATH_RE.test(href) || DOWNLOAD_QUERY_RE.test(href)) return true;
    if (DOWNLOAD_PATH_RE.test(onClick) || DOWNLOAD_QUERY_RE.test(onClick)) return true;

    const hrefLower = href.trim().toLowerCase();
    if (hrefLower.startsWith("javascript:") && hasFileHint(anchor)) return true;

    const url = normalizeUrl(href);
    if (FILE_RE.test(url)) return true;
    if (DOWNLOAD_PATH_RE.test(url) || DOWNLOAD_QUERY_RE.test(url)) return true;
    return hasFileHint(anchor);
  };

  document.addEventListener(
    "click",
    (event) => {
      const anchor = event.target && event.target.closest ? event.target.closest("a") : null;
      if (!anchor) return;
      if (!shouldOpenExternal(anchor)) return;
      event.preventDefault();
      const href = anchor.getAttribute("href");
      const url = normalizeUrl(href || "");
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
        window.pywebview.api.open_external(url);
      } else {
        window.open(url, "_blank");
      }
    },
    true
  );
})();
