"""Generate the SVG visual assets in assets/ (logo, hero, diagrams).

Run: python tools/make_assets.py
The SVGs are hand-designed here so they can be regenerated deterministically;
raster/logo variants for stores can be exported from these with any SVG tool.
"""
import os
import xml.dom.minidom

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
FONT = "Inter, Segoe UI, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, Consolas, monospace"
files: dict[str, str] = {}

files["logo.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 96" width="320" height="96" role="img" aria-label="RPython">
  <defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#2E6FDB"/><stop offset="1" stop-color="#F28C28"/></linearGradient></defs>
  <g transform="translate(8,8)">
    <path d="M14 6h30a20 20 0 0 1 0 40H26v28H14z M26 18v16h18a8 8 0 0 0 0-16z" fill="#2E6FDB"/>
    <path d="M30 46l24 28h-16L20 50z" fill="#2E6FDB" opacity=".9"/>
    <path d="M60 40c20-4 34-4 54 0" fill="none" stroke="url(#g)" stroke-width="6" stroke-linecap="round"/>
    <path d="M60 56c20 4 34 4 54 0" fill="none" stroke="url(#g)" stroke-width="6" stroke-linecap="round"/>
    <polygon points="112,32 124,40 112,48" fill="#F28C28"/><polygon points="62,48 50,56 62,64" fill="#2E6FDB"/>
    <path d="M148 8h20c14 0 24 8 24 22s-10 22-24 22h-8v22h-12z M160 20v20h8c8 0 12-4 12-10s-4-10-12-10z" fill="#F28C28"/>
  </g>
  <text x="212" y="58" font-family="{FONT}" font-size="30" font-weight="700" fill="#1F2A44">Python</text>
  <text x="212" y="80" font-family="{FONT}" font-size="12" fill="#5B6B8A">one research workspace</text>
</svg>
'''
files["logo-light.svg"] = files["logo.svg"]
files["logo-dark.svg"] = files["logo.svg"].replace('fill="#1F2A44"', 'fill="#FFFFFF"').replace('fill="#5B6B8A"', 'fill="#C9D6F2"')

files["icon.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="RPython icon">
  <rect width="64" height="64" rx="14" fill="#1F2A44"/>
  <text x="10" y="42" font-family="{FONT}" font-size="28" font-weight="800" fill="#7FB0FF">R</text>
  <path d="M28 26c6-2 10-2 16 0M28 38c6 2 10 2 16 0" fill="none" stroke="#F28C28" stroke-width="3" stroke-linecap="round"/>
  <polygon points="44,22 50,26 44,30" fill="#F28C28"/><polygon points="28,34 22,38 28,42" fill="#7FB0FF"/>
  <text x="48" y="44" font-family="{FONT}" font-size="16" font-weight="800" fill="#FFC27A">Py</text>
</svg>
'''

files["hero.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300" width="1200" height="300" role="img" aria-label="RPython hero">
  <defs>
    <linearGradient id="bg" x1="0" x2="1"><stop offset="0" stop-color="#1F2A44"/><stop offset="1" stop-color="#2E4A7A"/></linearGradient>
    <linearGradient id="bridge" x1="0" x2="1"><stop offset="0" stop-color="#7FB0FF"/><stop offset="1" stop-color="#FFC27A"/></linearGradient>
  </defs>
  <rect width="1200" height="300" rx="24" fill="url(#bg)"/>
  <g font-family="{FONT}" fill="#FFFFFF">
    <text x="60" y="110" font-size="44" font-weight="800">R and Python, one seamless research workspace.</text>
    <text x="60" y="152" font-size="19" fill="#C9D6F2">Native R stays R. Native Python stays Python. RPython moves data, models, plots and databases</text>
    <text x="60" y="180" font-size="19" fill="#C9D6F2">between them without losing what they mean: factors, time zones, panels, CRS, graph topology, sparsity.</text>
  </g>
  <g transform="translate(60,215)" font-family="{MONO}" font-size="15" fill="#E8EEFC">
    <rect width="1080" height="56" rx="10" fill="#0F1930" opacity=".8"/>
    <text x="18" y="24">r = rp.R();  r["df"] = panel;  fit = r("plm(y ~ x, data = df, model = &quot;within&quot;)");  fit.coef()</text>
    <text x="18" y="46" fill="#FFC27A">library(rpython); py &lt;- python(); sk &lt;- py$package("sklearn.linear_model"); m &lt;- sk$LinearRegression()$fit(X, y)</text>
  </g>
  <g transform="translate(880,40)">
    <circle cx="70" cy="70" r="56" fill="#0F1930" opacity=".7"/>
    <text x="42" y="90" font-family="{FONT}" font-size="52" font-weight="800" fill="#7FB0FF">R</text>
    <circle cx="230" cy="70" r="56" fill="#0F1930" opacity=".7"/>
    <text x="196" y="88" font-family="{FONT}" font-size="40" font-weight="800" fill="#FFC27A">Py</text>
    <path d="M130 58c26-10 44-10 70 0" fill="none" stroke="url(#bridge)" stroke-width="7" stroke-linecap="round"/>
    <path d="M130 82c26 10 44 10 70 0" fill="none" stroke="url(#bridge)" stroke-width="7" stroke-linecap="round"/>
    <polygon points="198,48 212,58 198,68" fill="#FFC27A"/><polygon points="132,72 118,82 132,92" fill="#7FB0FF"/>
  </g>
</svg>
'''

files["architecture.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 560" width="1000" height="560" font-family="{FONT}">
  <style>.box{{fill:#F4F7FD;stroke:#2E6FDB;stroke-width:2}}.py{{fill:#FFF4E8;stroke:#F28C28}}.t{{font-size:14px;fill:#1F2A44}}.h{{font-size:17px;font-weight:700;fill:#1F2A44}}.s{{font-size:12px;fill:#5B6B8A}}.a{{stroke:#5B6B8A;stroke-width:2;fill:none;marker-end:url(#m)}}</style>
  <defs><marker id="m" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5 0 10z" fill="#5B6B8A"/></marker></defs>
  <text x="500" y="34" text-anchor="middle" class="h" font-size="22">RPython architecture</text>
  <rect x="40" y="70" width="920" height="90" rx="10" class="box py"/><text x="60" y="98" class="h">Public API (Python package) / rpython R package</text>
  <text x="60" y="122" class="t">rp.R() · r("code") · r["x"] = obj · r.package() · proxies · rp.panel / timeseries / spatial / network · rp.connect · rp.save/load · %%r magics · rp.doctor / explain_last · python() from R</text>
  <text x="60" y="146" class="s">Beginner: one line per operation. Advanced: transfer backend, lossy/missing policy, memory threshold, raw envelopes, custom adapters.</text>
  <rect x="40" y="190" width="440" height="150" rx="10" class="box"/><text x="60" y="218" class="h">Semantic data layer</text>
  <text x="60" y="244" class="t">Detection → classification (confirmed / inferred / suggestion)</text>
  <text x="60" y="266" class="t">Type negotiation → transfer plan (json / arrow-ipc / shared file / lazy / proxy)</text>
  <text x="60" y="288" class="t">Adapters per family: registry, tiers A→E, fidelity report</text>
  <text x="60" y="310" class="s">src/rpython/data/* · memory guard · Explain Mode history</text>
  <rect x="520" y="190" width="440" height="150" rx="10" class="box"/><text x="540" y="218" class="h">Database layer</text>
  <text x="540" y="244" class="t">ConnectionRef (secret-free) + SecretVault</text>
  <text x="540" y="266" class="t">Lazy Relation: pushdown, bound params, Arrow batches</text>
  <text x="540" y="288" class="t">Adapters: SQL · DuckDB · lakes · document · KV · graph · TS · vector · search</text>
  <text x="540" y="310" class="s">src/rpython/database/*</text>
  <rect x="40" y="370" width="920" height="70" rx="10" class="box"/><text x="60" y="398" class="h">Portable envelope (RPX)</text>
  <text x="60" y="422" class="t">JSON with explicit NA/NaN/Inf tokens + semantic sidecars · Arrow IPC files for columnar payloads · WKB for geometry · handles for proxies · shared paths for files / databases</text>
  <rect x="40" y="470" width="440" height="70" rx="10" class="box py"/><text x="60" y="498" class="h">R companion package (isolated Rscript worker)</text>
  <text x="60" y="522" class="t">rpx_encode / rpx_decode · sf, igraph, Matrix, xts, haven, survival, plm, terra …</text>
  <rect x="520" y="470" width="440" height="70" rx="10" class="box py"/><text x="540" y="498" class="h">Python worker (driven by R)</text>
  <text x="540" y="522" class="t">same protocol · pandas, numpy, sklearn, torch … · object store for proxies</text>
  <path d="M260 160v30" class="a"/><path d="M740 160v30" class="a"/><path d="M260 340v30" class="a"/><path d="M740 340v30" class="a"/><path d="M260 440v30" class="a"/><path d="M740 440v30" class="a"/>
</svg>
'''

files["workflow.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 200" width="1000" height="200" font-family="{FONT}">
  <style>.b{{fill:#F4F7FD;stroke:#2E6FDB;stroke-width:2}}.t{{font-size:14px;fill:#1F2A44;font-weight:700}}.s{{font-size:12px;fill:#5B6B8A}}.a{{stroke:#5B6B8A;stroke-width:2;fill:none;marker-end:url(#m)}}</style>
  <defs><marker id="m" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5 0 10z" fill="#5B6B8A"/></marker></defs>
  <rect x="20" y="50" width="140" height="80" rx="10" class="b"/><text x="90" y="82" text-anchor="middle" class="t">Detection</text><text x="90" y="104" text-anchor="middle" class="s">what is this object?</text>
  <rect x="185" y="50" width="140" height="80" rx="10" class="b"/><text x="255" y="82" text-anchor="middle" class="t">Classification</text><text x="255" y="104" text-anchor="middle" class="s">confirmed / suggested</text>
  <rect x="350" y="50" width="140" height="80" rx="10" class="b"/><text x="420" y="82" text-anchor="middle" class="t">Negotiation</text><text x="420" y="104" text-anchor="middle" class="s">capabilities, size, cost</text>
  <rect x="515" y="50" width="140" height="80" rx="10" class="b"/><text x="585" y="82" text-anchor="middle" class="t">Best path</text><text x="585" y="104" text-anchor="middle" class="s">native / Arrow / adapter / lazy</text>
  <rect x="680" y="50" width="140" height="80" rx="10" class="b"/><text x="750" y="82" text-anchor="middle" class="t">Fidelity check</text><text x="750" y="104" text-anchor="middle" class="s">values, types, index, CRS …</text>
  <rect x="845" y="50" width="140" height="80" rx="10" fill="#FFF4E8" stroke="#F28C28" stroke-width="2"/><text x="915" y="82" text-anchor="middle" class="t">Proxy fallback</text><text x="915" y="104" text-anchor="middle" class="s">object stays native</text>
  <path d="M160 90h25M325 90h25M490 90h25M655 90h25M820 90h25" class="a"/>
  <text x="500" y="170" text-anchor="middle" class="s">Every step is recorded: rp.explain_last() shows the plan, the notes, the risks and the fidelity report.</text>
</svg>
'''

rows = [("int/float/str/bytes/Decimal/datetime", "Primitives · native JSON", "logical/integer/double/character/raw/Date/POSIXct"),
        ("list · dict · tuple · dataclass", "Collections · recursive, cycle-safe", "vector · named list"),
        ("numpy · torch · jax · masked", "Arrays · explicit memory order", "matrix · array (dimnames)"),
        ("scipy.sparse csc/csr/coo", "Sparse · never densified", "Matrix dgC/dgR/dgT"),
        ("pandas · polars · pyarrow · interchange", "Tabular · Arrow IPC + sidecar", "data.frame · tibble · data.table · arrow"),
        ("DatetimeIndex · PeriodIndex · rp.timeseries", "Time series · freq, tz, gaps", "ts · mts · xts · zoo · tsibble"),
        ("rp.panel · cross-section · repeated CS", "Panel · balance, gaps, keys", "plm::pdata.frame · attributes"),
        ("rp.labelled · pyreadstat · rp.survival", "Survey · Survival", "haven::labelled · survival::Surv"),
        ("GeoDataFrame · shapely · rasterio · xarray", "Spatial · Raster · Sci-arrays · WKB/CRS", "sf · terra · stars"),
        ("networkx · igraph · triples", "Networks · direction, multi-edges", "igraph · tidygraph"),
        ("DTM · corpus · Image · Audio · Video", "Text · Media · metadata kept", "quanteda · arrays + attributes"),
        ("rp.connect · Relation · datasets", "Databases · shared, lazy, 0 copies", "DBI · dbplyr · duckdb · arrow"),
        ("sklearn models · custom classes · generators", "Anything else · native proxy", "lm/glm/S4/R6 · package objects")]
body = ""
for i, (a, b, c) in enumerate(rows):
    y = 80 + i * 32
    dash = ' style="stroke-dasharray:4"' if i == len(rows) - 1 else ""
    body += (f'  <g transform="translate(0,{y})"><rect x="40" y="0" width="290" height="26" rx="6" class="py"{dash}/><text x="50" y="18">{a}</text>'
             f'<text x="500" y="18" class="c">{b}</text><rect x="670" y="0" width="290" height="26" rx="6" class="r"{dash}/><text x="680" y="18">{c}</text>'
             f'<path d="M330 13h340" class="l"{dash}/></g>\n')
files["conversion-map.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 520" width="1000" height="520" font-family="{FONT}">
  <style>.py{{fill:#FFF4E8;stroke:#F28C28;stroke-width:1.5}}.r{{fill:#F4F7FD;stroke:#2E6FDB;stroke-width:1.5}}text{{font-size:12.5px;fill:#1F2A44}}.h{{font-size:18px;font-weight:700;fill:#1F2A44}}.c{{font-size:12px;fill:#5B6B8A;text-anchor:middle}}.l{{stroke:#9AA8C7;stroke-width:1.5}}</style>
  <text x="500" y="30" text-anchor="middle" class="h">Data Universe — what crosses the bridge, and how</text>
  <text x="185" y="62" text-anchor="middle" class="h" fill="#F28C28">Python</text><text x="500" y="62" text-anchor="middle" class="h">family · path</text><text x="815" y="62" text-anchor="middle" class="h" fill="#2E6FDB">R</text>
{body}</svg>
'''

files["notebook-demo.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 330" width="900" height="330" font-family="{MONO}" font-size="14">
  <rect width="900" height="330" rx="12" fill="#FFFFFF" stroke="#D8E0F0"/>
  <text x="24" y="34" font-family="{FONT}" font-size="16" font-weight="700" fill="#1F2A44">Jupyter / Colab — mixed-language cells</text>
  <rect x="24" y="52" width="852" height="88" rx="8" fill="#F7F9FE" stroke="#D8E0F0"/>
  <text x="40" y="76" fill="#5B6B8A">[1]</text><text x="72" y="76" fill="#1F2A44">import rpython as rp, pandas as pd</text>
  <text x="72" y="98" fill="#1F2A44">rp.setup()</text>
  <text x="72" y="120" fill="#1F2A44">panel = rp.panel(pd.read_parquet("trade.parquet"), id="country", time="year")</text>
  <rect x="24" y="152" width="852" height="88" rx="8" fill="#FFF8F0" stroke="#F5D9B8"/>
  <text x="40" y="176" fill="#5B6B8A">[2]</text><text x="72" y="176" fill="#B45309">%%r -i panel -o fit</text>
  <text x="72" y="198" fill="#1F2A44">library(plm)</text>
  <text x="72" y="220" fill="#1F2A44">fit &lt;- plm(exports ~ gdp + tariff, data = panel, model = "within")</text>
  <rect x="24" y="252" width="852" height="60" rx="8" fill="#F7F9FE" stroke="#D8E0F0"/>
  <text x="40" y="276" fill="#5B6B8A">[3]</text><text x="72" y="276" fill="#1F2A44">fit.summary()        # R summary.plm proxy; fit.coef() -> pandas</text>
  <text x="72" y="298" fill="#1F2A44">rp.explain_last()    # panel keys, balance, Arrow IPC, fidelity report</text>
</svg>
'''

files["result-object.svg"] = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="900" height="300" font-family="{FONT}">
  <style>.k{{font-size:14px;fill:#2E6FDB;font-weight:700}}.v{{font-size:13px;fill:#1F2A44}}.h{{font-size:17px;font-weight:700;fill:#1F2A44}}</style>
  <rect width="900" height="300" rx="12" fill="#F4F7FD" stroke="#D8E0F0"/>
  <text x="24" y="36" class="h">res = r.eval("fit &lt;- lm(mpg ~ wt, mtcars); plot(fit); summary(fit)")</text>
  <g transform="translate(24,60)">
    <text x="0" y="24" class="k">res.value</text><text x="230" y="24" class="v">R summary.lm proxy — res.value.r_squared → 0.753, res.value.coefficients → array</text>
    <text x="0" y="52" class="k">res.stdout</text><text x="230" y="52" class="v">captured console output (never lost)</text>
    <text x="0" y="80" class="k">res.messages / res.warnings</text><text x="230" y="80" class="v">R messages and warnings as lists</text>
    <text x="0" y="108" class="k">res.plots / res.plot</text><text x="230" y="108" class="v">PNG files with notebook display and .save("fig.svg")</text>
    <text x="0" y="136" class="k">res.table / res.model</text><text x="230" y="136" class="v">typed views when the value is a DataFrame / model proxy</text>
    <text x="0" y="164" class="k">res.raw</text><text x="230" y="164" class="v">the wire reply for advanced debugging</text>
    <text x="0" y="192" class="k">r("1 + 1")</text><text x="230" y="192" class="v">plain values come back as plain Python (2.0) — no wrapper for scalars</text>
  </g>
</svg>
'''

if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(content)
        xml.dom.minidom.parse(os.path.join(ROOT, name))   # well-formedness check
    print("wrote", ", ".join(sorted(files)))
