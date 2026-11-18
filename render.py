"""Abre tweet-a-imagen.html en un Chromium sin pantalla, rellena los datos y saca la captura 2560x1440."""
from pathlib import Path

HTML = Path(__file__).with_name("tweet-a-imagen.html").resolve().as_uri()

FILL_JS = """
(d) => {
  const g = id => document.getElementById(id);
  for (const k of ["name","handle","text","date","rep","rt","lk","vw"]) g(k).value = d[k];
  g("ver").value = d.verified ? "1" : "0";
  g("theme").value = d.theme === "dark" ? "dark" : "light";
  ["sDate","sRep","sRt","sLk","sVw"].forEach(i => g(i).checked = !d.clean);
  g("pAv").style.backgroundImage = d.avatar ? `url(${d.avatar})` : "";
  if (d.avatar) g("pAv").textContent = "";
  const sw = document.querySelectorAll(".sw"); if (sw[d.bg]) sw[d.bg].click();
  setMedia(d.media || "");
  upd();
}
"""

async def render(browser, d):
    ctx = await browser.new_context(viewport={"width": 1800, "height": 900}, device_scale_factor=2)
    try:
        page = await ctx.new_page()
        # El bot no necesita html2canvas (solo sirve para el botón de descarga de la web)
        await page.route("**/cdnjs.cloudflare.com/**", lambda r: r.abort())
        await page.goto(HTML)
        await page.evaluate(FILL_JS, d)
        await page.wait_for_timeout(500)
        return await page.locator("#canvas").screenshot(type="png")
    finally:
        await ctx.close()
