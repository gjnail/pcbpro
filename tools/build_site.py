"""Build the website (GitHub Pages) into _site/: the pages in site/, the guides in docs/*.md turned into HTML, the
examples gallery, the sound clips and the media in docs/media.

    python tools/build_site.py            # needs only Python-Markdown (pip install markdown)
    python tools/build_site.py --serve    # build, then serve _site on http://localhost:8000
    python tools/build_site.py --check    # build, and fail on a broken link between the guides

The guides are plain Markdown and read fine on GitHub too. On the site, an image of an animated GIF in
docs/media/gif/NAME.gif is shown as the sharper video docs/media/video/NAME.mp4 when there is one, and an image's
title ("...") becomes its caption. docs/examples.md is written from docs/examples.json on every build, so the
gallery on GitHub and on the site always agree.
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE, DOCS, OUT = ROOT / 'site', ROOT / 'docs', ROOT / '_site'
REPO = 'https://github.com/gjnail/pcbpro'
BASE_URL = 'https://gjnail.github.io/pcbpro/'
DOWNLOAD = f'{REPO}/releases/latest'
KOFI = 'https://ko-fi.com/gnail'

# (group, slug, short title for the menus). The page title is the guide's own first heading.
GUIDES = [
    ('Start here', 'getting-started', 'Install and first steps'),
    ('Start here', 'tutorial', 'Tutorial: your first pedal'),
    ('Start here', 'examples', 'Examples'),
    ('Design', 'layout', 'The layout editor'),
    ('Design', 'library', 'The parts library'),
    ('Design', '3d-view', 'The 3D view'),
    ('Pedals and amps', 'pedals', 'Guitar pedals'),
    ('Pedals and amps', 'amp-designer', 'The Amp Designer'),
    ('Pedals and amps', 'high-gain', 'High-gain amps and metal pedals'),
    ('Pedals and amps', 'amps', 'Amp boards and high voltage'),
    ('Simulate', 'simulation', 'Running the board'),
    ('Simulate', 'firmware', 'Microcontrollers and firmware'),
    ('Simulate', 'audio', 'Playing guitar through it'),
    ('Build it', 'manufacturing', 'Manufacturing and ordering'),
    ('Build it', 'buying-parts', 'Buying components'),
    ('Reference', 'shortcuts', 'Shortcuts and command line'),
    ('Reference', 'how-it-works', 'How it works'),
    ('Reference', 'troubleshooting', 'Troubleshooting and limits'),
]
GUIDE_SLUGS = {g[1] for g in GUIDES}

FILTERS = [('all', 'All'), ('pedal', 'Pedals'), ('amp', 'Amps'), ('board', 'Boards')]
CATEGORY_LABEL = {'pedal': 'Pedal', 'amp': 'Amp', 'board': 'Board'}

NAV = [('tutorial', 'Tutorial', 'tutorial.html'), ('guides', 'Guides', 'guides.html'),
       ('examples', 'Examples', 'examples.html'), ('listen', 'Listen', 'index.html#listen'), ('github', 'GitHub', REPO)]


def esc(s):
    return html.escape(str(s), quote=True)


# ---- page shell -------------------------------------------------------------------------------------------

def head(title, description, path, image='media/img/og.jpg'):
    full = title if title.startswith('PCBPro') else f'{title} · PCBPro'
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(full)}</title>
  <meta name="description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(full)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:image" content="{BASE_URL}{image}">
  <meta property="og:url" content="{BASE_URL}{path}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#0b0d10">
  <link rel="icon" href="media/img/icon-64.png" type="image/png">
  <link rel="preload" href="assets/fonts/barlow-700.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>'''


def header(current):
    links = []
    for key, label, href in NAV:
        cur = ' aria-current="page"' if key == current else ''
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    links.append(f'<a class="btn btn-primary btn-small" href="{DOWNLOAD}">Download</a>')
    return f'''<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="index.html"><img src="media/img/icon-64.png" alt="" width="28" height="28">PCBPro</a>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
    <nav class="site-nav" id="site-nav" aria-label="Main">
      {"".join(links)}
    </nav>
  </div>
</header>'''


def footer():
    return f'''<footer class="site-footer">
  <div class="footer-inner">
    <div>PCBPro · PCB design for guitar pedals, amps and everything else · MIT license</div>
    <nav aria-label="Footer">
      <a href="getting-started.html">Install</a>
      <a href="guides.html">Guides</a>
      <a href="examples.html">Examples</a>
      <a href="{REPO}">Source</a>
      <a href="{REPO}/blob/main/CHANGELOG.md">Changelog</a>
      <a href="{REPO}/issues">Report a problem</a>
      <a href="{KOFI}">Support on Ko-fi</a>
    </nav>
  </div>
</footer>
<script src="assets/site.js" defer></script>
</body>
</html>
'''


# ---- media helpers -------------------------------------------------------------------------------------------

def video_tag(name, caption=None, label=None, cls='media'):
    """A looping, muted clip that plays while on screen (media/video/NAME.mp4 with its poster)."""
    v = (f'<video data-loop muted loop playsinline preload="none" poster="media/video/{name}.jpg">'
         f'<source src="media/video/{name}.mp4" type="video/mp4"></video>')
    lab = f'<span class="label">{esc(label)}</span>' if label else ''
    cap = f'<figcaption>{caption}</figcaption>' if caption else ''
    return f'<figure><div class="{cls}">{v}{lab}</div>{cap}</figure>'


def image_tag(src, caption=None, label=None, cls='media', alt=''):
    lab = f'<span class="label">{esc(label)}</span>' if label else ''
    cap = f'<figcaption>{caption}</figcaption>' if caption else ''
    return (f'<figure><div class="{cls}"><img src="media/{src}" alt="{esc(alt or label or "")}" loading="lazy">'
            f'{lab}</div>{cap}</figure>')


IMG_P = re.compile(r'<p>\s*((?:<img [^>]*>\s*)+)</p>')
IMG = re.compile(r'<img [^>]*>')
IMG_ATTR = re.compile(r'(\w+)="([^"]*)"')


def figure(img_tag):
    """One image -> a figure: a GIF that has a video becomes the video; its title becomes the caption."""
    attrs = dict(IMG_ATTR.findall(img_tag))
    src, alt, title = attrs.get('src', ''), attrs.get('alt', ''), attrs.get('title')
    cap = f'<figcaption>{title}</figcaption>' if title else ''
    g = re.fullmatch(r'media/gif/([\w-]+)\.gif', src)
    if g and (DOCS / 'media' / 'video' / f'{g.group(1)}.mp4').exists():
        name = g.group(1)
        return (f'<figure><video data-loop muted loop playsinline preload="none" aria-label="{alt}" '
                f'poster="media/video/{name}.jpg"><source src="media/video/{name}.mp4" type="video/mp4"></video>'
                f'{cap}</figure>')
    return f'<figure><img src="{src}" alt="{alt}" loading="lazy">{cap}</figure>'


def figures(body):
    """<p><img></p> -> a figure; several images in one paragraph (side by side on GitHub) -> a grid."""
    def fig(m):
        imgs = IMG.findall(m.group(1))
        if len(imgs) == 1:
            return figure(imgs[0])
        return '<div class="grid2">' + ''.join(figure(t) for t in imgs) + '</div>'
    return IMG_P.sub(fig, body)


def links(body):
    """Markdown links between the docs and to the source -> site links."""
    def fix(m):
        href = m.group(1)
        if re.match(r'^[a-z]+:', href) or href.startswith('#'):
            return m.group(0)
        path, _, frag = href.partition('#')
        frag = f'#{frag}' if frag else ''
        if path.endswith('.md') and Path(path).stem in GUIDE_SLUGS and '/' not in path.strip('./'):
            return f'href="{Path(path).stem}.html{frag}"'
        if path in ('../README.md', 'README.md'):
            return f'href="{REPO}#readme"'
        if path.startswith('../'):
            kind = 'tree' if path.endswith('/') else 'blob'
            return f'href="{REPO}/{kind}/main/{path[3:]}{frag}"'
        return m.group(0)
    return re.sub(r'href="([^"]+)"', fix, body)


# ---- guides ----------------------------------------------------------------------------------------------------

def render_md(text):
    import markdown
    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'attr_list', 'md_in_html', 'sane_lists', 'toc'],
                           extension_configs={'toc': {'permalink': '#', 'toc_depth': '2-3'}})
    body = md.convert(text)
    return body, md.toc_tokens


def doc_nav(current):
    out, group = [], None
    for g, slug, short in GUIDES:
        if g != group:
            out.append(f'<h4>{esc(g)}</h4>')
            group = g
        cur = ' aria-current="page"' if slug == current else ''
        out.append(f'<a href="{slug}.html"{cur}>{esc(short)}</a>')
    return ('<aside class="doc-nav" aria-label="Guides"><button class="doc-nav-toggle" type="button" '
            'aria-expanded="false">All guides</button><div class="doc-nav-list">' + ''.join(out) + '</div></aside>')


def toc_html(tokens):
    def walk(ts):
        items = []
        for t in ts:
            kids = walk(t['children']) if t['children'] else ''
            items.append(f'<li><a href="#{t["id"]}">{t["name"]}</a>{kids}</li>')
        return f'<ul>{"".join(items)}</ul>' if items else ''
    h2 = tokens[0]['children'] if tokens and tokens[0]['level'] == 1 else tokens
    if not h2:
        return ''
    flat = [dict(t, children=[c for c in t['children'] if c['level'] == 3]) for t in h2]
    return f'<nav class="toc" aria-label="On this page"><h4>On this page</h4>{walk(flat)}</nav>'


def build_guide(i, slug, anchors):
    src = DOCS / f'{slug}.md'
    text = src.read_text(encoding='utf-8')
    body, tokens = render_md(text)
    anchors[slug] = set(re.findall(r'\sid="([^"]+)"', body))
    m = re.search(r'<h1[^>]*>(.*?)</h1>', body, re.S)
    title = re.sub(r'<[^>]+>', '', m.group(1)).replace('#', '').strip() if m else slug
    # the first paragraph after the title is the page's introduction
    body = re.sub(r'(</h1>\s*)<p>', r'\1<p class="intro">', body, count=1)
    intro = re.search(r'<p class="intro">(.*?)</p>', body, re.S)
    desc = re.sub(r'<[^>]+>', '', intro.group(1)).strip() if intro else title
    desc = (desc[:240] + '…') if len(desc) > 240 else desc
    body = links(figures(body))
    prev_g = GUIDES[i - 1] if i > 0 else None
    next_g = GUIDES[i + 1] if i + 1 < len(GUIDES) else None
    pager = '<nav class="pager" aria-label="Previous and next">'
    pager += (f'<a class="prev" href="{prev_g[1]}.html"><small>Previous</small><b>{esc(prev_g[2])}</b></a>'
              if prev_g else '<span></span>')
    pager += (f'<a class="next" href="{next_g[1]}.html"><small>Next</small><b>{esc(next_g[2])}</b></a>'
              if next_g else '<span></span>')
    pager += '</nav>'
    page = (head(title, desc, f'{slug}.html') + header('tutorial' if slug == 'tutorial' else
                                                      'examples' if slug == 'examples' else 'guides') +
            f'<main id="main" class="doc">{doc_nav(slug)}<article class="prose">{body}'
            f'<p class="caption">Something wrong or missing on this page? <a href="{REPO}/edit/main/docs/{slug}.md">'
            f'Edit it on GitHub</a>.</p>{pager}</article>{toc_html(tokens)}</main>' + footer())
    (OUT / f'{slug}.html').write_text(page, encoding='utf-8')
    return title, desc, text


def check_links(texts, anchors):
    """Links between the guides must point at a guide that exists and a heading it has."""
    bad = []
    for slug, text in texts.items():
        for href in re.findall(r'\]\(([^)\s]+)', text):
            if re.match(r'^[a-z]+:', href):
                continue
            path, _, frag = href.partition('#')
            if not path:
                target = slug
            elif path.endswith('.md') and '/' not in path:
                target = Path(path).stem
                if target not in GUIDE_SLUGS:
                    bad.append(f'{slug}.md: {href} (no such guide)')
                    continue
            else:
                if not (DOCS / path).exists():
                    bad.append(f'{slug}.md: {href} (no such file)')
                continue
            if frag and frag not in anchors.get(target, set()):
                bad.append(f'{slug}.md: {href} (no such heading)')
    return bad


def build_guides_index(info):
    cards, group = [], None
    blurb_media = json.loads((SITE / 'guides.json').read_text(encoding='utf-8'))
    for g, slug, short in GUIDES:
        if g != group:
            if group is not None:
                cards.append('</div>')
            cards.append(f'<h2 class="group-title">{esc(g)}</h2><div class="cards">')
            group = g
        title, desc, _ = info[slug]
        thumb = blurb_media.get(slug, {})
        img = thumb.get('image', 'media/img/og.jpg')
        text = thumb.get('blurb', desc)
        cards.append(f'<a class="card" href="{slug}.html"><img src="{img}" alt="" loading="lazy" width="640" height="360">'
                     f'<div class="card-body"><h3>{esc(short)}</h3><p>{esc(text)}</p></div></a>')
    cards.append('</div>')
    page = (head('Guides', 'Every part of PCBPro explained: pedals, amps and the Amp Designer, layout and routing, the '
                 'parts library, simulation and playing guitar through your board, and ordering.', 'guides.html') +
            header('guides') +
            '<main id="main"><section class="section"><div class="section-head"><p class="kicker">Guides</p>'
            '<h1 class="page-title">Everything PCBPro does, and how to use it</h1><p class="sub">Start with the '
            'install guide and the tutorial. Every other guide stands on its own: read the one for what you are '
            'building.</p></div>' + ''.join(cards) + '</section></main>' + footer())
    (OUT / 'guides.html').write_text(page, encoding='utf-8')


# ---- examples --------------------------------------------------------------------------------------------------

def examples():
    return json.loads((DOCS / 'examples.json').read_text(encoding='utf-8'))


def refresh_examples_md():
    """docs/examples.md, the gallery for reading on GitHub (the site builds examples.html from the same JSON)."""
    rows = examples()
    md = ['# Examples', '',
          f'PCBPro comes with {len(rows)} example projects, every one placed, routed and passing its design rule '
          'check. Open one, change anything, and save it as your own. Each can be simulated, and the pedals and amps '
          'can be played through. On the website the gallery is at <https://gjnail.github.io/pcbpro/examples.html>.',
          '']
    for key, label in FILTERS[1:]:
        group = [r for r in rows if r['category'] == key]
        if not group:
            continue
        md += [f'## {label}', '', '| | Example | Notes |', '|---|---|---|']
        for r in group:
            img = f'media/examples/{r["file"]}{"-box" if r.get("box") else ""}.webp'
            md.append(f'| <img src="{img}" width="240" alt=""> | **{r["name"]}**<br>{r["size"]}<br>'
                      f'*{r["open"]}* | {r["blurb"]} |')
        md.append('')
    md += ['The project files are in [`pcbpro/resources/examples`](../pcbpro/resources/examples/). '
           '`tools/build_examples.py` rebuilds them from their generators.', '']
    text = '\n'.join(md)
    path = DOCS / 'examples.md'
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8', newline='\n')


def build_examples_page():
    rows = examples()
    chips = ''.join(f'<button type="button" data-cat="{k}" aria-pressed="{"true" if k == "all" else "false"}">'
                    f'{esc(v)}</button>' for k, v in FILTERS)
    cards = []
    for r in rows:
        f = r['file']
        box = f'<img class="alt" src="media/examples/{f}-box.webp" alt="" loading="lazy" width="640" height="360">' \
            if r.get('box') else ''
        cards.append(f'<article class="preset" data-cat="{r["category"]}" id="{f}" tabindex="0"><div class="thumb">'
                     f'<img src="media/examples/{f}.webp" alt="" loading="lazy" width="640" height="360">{box}'
                     f'{"<span class=play>In the box</span>" if box else ""}</div>'
                     f'<div class="body"><h3>{esc(r["name"])}</h3><p class="meta">{CATEGORY_LABEL[r["category"]]} · '
                     f'{esc(r["size"])}</p><p>{esc(r["blurb"])}</p><p class="open">{esc(r["open"])}</p></div></article>')
    page = (head('Examples', f'{len(rows)} example projects that ship with PCBPro: pedals, tube and solid-state amps '
                 'and a 555 flasher, every one routed, checked and playable.', 'examples.html',
                 'media/examples/Amp_Modern_High_Gain_50W.webp') + header('examples') +
            '<main id="main"><section class="section" style="padding-top:56px"><div class="section-head">'
            f'<p class="kicker">Examples</p><h1 class="page-title">{len(rows)} boards to start from</h1>'
            '<p class="sub">Every example is placed, routed and passes its design rule check. Open one, run it, play '
            'through it, change anything and save it as your own. Hover a pedal to see it in its box.</p></div>'
            f'<div class="filters" role="group" aria-label="Filter examples">{chips}</div>'
            f'<div class="preset-grid">{"".join(cards)}</div></section></main>' + footer())
    (OUT / 'examples.html').write_text(page, encoding='utf-8')


# ---- sound clips -----------------------------------------------------------------------------------------------

def clips_html(keys):
    """{{clips|a,b,c}}: audio players for the clips in docs/media/audio/clips.json."""
    path = DOCS / 'media' / 'audio' / 'clips.json'
    if not path.exists():
        return ''
    by_key = {c['key']: c for c in json.loads(path.read_text(encoding='utf-8'))}
    out = []
    for k in [k.strip() for k in keys.split(',') if k.strip()]:
        c = by_key.get(k)
        if c is None:
            raise SystemExit(f'site: no sound clip "{k}" in docs/media/audio/clips.json')
        out.append(f'<figure class="clip-audio"><figcaption><b>{esc(c["title"])}</b><span>{esc(c["caption"])}'
                   f'</span></figcaption><audio controls preload="none" src="media/audio/{k}.mp3"></audio></figure>')
    return ''.join(out)


# ---- static pages ---------------------------------------------------------------------------------------------

def build_static():
    """site/*.html: {{head|TITLE|DESCRIPTION|PATH}}, {{header|KEY}}, {{footer}}, {{video|NAME|CAPTION|LABEL}},
    {{image|SRC|CAPTION|LABEL}}, {{clips|KEY,KEY}}, {{example_count}}."""
    count = len(examples())
    for src in SITE.glob('*.html'):
        text = src.read_text(encoding='utf-8').replace('{{example_count}}', str(count))
        text = text.replace('{{download}}', DOWNLOAD).replace('{{repo}}', REPO).replace('{{kofi}}', KOFI)
        text = re.sub(r'\{\{head\|([^|]*)\|([^|]*)\|([^}]*)\}\}', lambda m: head(m.group(1), m.group(2), m.group(3)), text)
        text = re.sub(r'\{\{header\|([^}]*)\}\}', lambda m: header(m.group(1)), text)
        text = text.replace('{{footer}}', footer())
        text = re.sub(r'\{\{video\|([^|}]*)\|?([^|}]*)\|?([^}]*)\}\}',
                      lambda m: video_tag(m.group(1), m.group(2) or None, m.group(3) or None), text)
        text = re.sub(r'\{\{image\|([^|}]*)\|?([^|}]*)\|?([^}]*)\}\}',
                      lambda m: image_tag(m.group(1), m.group(2) or None, m.group(3) or None), text)
        text = re.sub(r'\{\{clips\|([^}]*)\}\}', lambda m: clips_html(m.group(1)), text)
        if src.name == '404.html':   # served for any missing path, so its links must not be relative to it
            text = text.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <base href="/pcbpro/">', 1)
        leftover = re.search(r'\{\{[^}]*\}\}', text)
        if leftover:
            raise SystemExit(f'site/{src.name}: unknown template tag {leftover.group(0)}')
        (OUT / src.name).write_text(text, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--serve', action='store_true', help='serve _site on http://localhost:8000 after building')
    ap.add_argument('--check', action='store_true', help='fail on a broken link between the guides')
    args = ap.parse_args()
    refresh_examples_md()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(SITE / 'assets', OUT / 'assets')
    shutil.copytree(DOCS / 'media', OUT / 'media')
    (OUT / '.nojekyll').write_text('')
    build_static()
    info, anchors = {}, {}
    for i, (_, slug, _) in enumerate(GUIDES):
        info[slug] = build_guide(i, slug, anchors)
    build_guides_index(info)
    build_examples_page()
    bad = check_links({slug: v[2] for slug, v in info.items()}, anchors)
    for b in bad:
        print('broken link:', b)
    pages = sorted(p.name for p in OUT.glob('*.html'))
    with open(OUT / 'sitemap.xml', 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for p in pages:
            if p != '404.html':
                fh.write(f'  <url><loc>{BASE_URL}{"" if p == "index.html" else p}</loc></url>\n')
        fh.write('</urlset>\n')
    print(f'built {len(pages)} pages into {OUT}')
    if bad and args.check:
        sys.exit(1)
    if args.serve:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print('serving on http://localhost:8000')
        http.server.ThreadingHTTPServer(('127.0.0.1', 8000), handler).serve_forever()


if __name__ == '__main__':
    main()
