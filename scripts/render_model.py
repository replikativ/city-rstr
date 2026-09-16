#!/usr/bin/env python3
"""doc/model.md -> public/model.html: the model explanation the explorer links to.
Run from the repository root: python3 scripts/render_model.py
A deliberately small Markdown subset — headings, paragraphs, fenced code,
pipe tables, lists, links, emphasis, inline code — no dependency."""
import html, re, sys
src = open('doc/model.md', encoding='utf-8').read().splitlines()
out, i, para = [], 0, []
MATH = []
def stash_math(t):
    # MathJax reads the DOM text, so a formula must pass through untouched:
    # neither escaped for emphasis nor rewritten as a link
    def keep(m):
        MATH.append(html.escape(m.group(0), quote=False)); return '\x00%d\x00' % (len(MATH) - 1)
    return re.sub(r'\\\((?:.|\n)*?\\\)', keep, t)
def unstash(t):
    return re.sub(r'\x00(\d+)\x00', lambda m: MATH[int(m.group(1))], t)
def inline(t):
    t = stash_math(t)
    t = html.escape(t, quote=False)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<![\w*])\*([^*\n]+)\*(?!\w)', r'<em>\1</em>', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: '<a href="%s">%s</a>' % (m.group(2).replace('.md', '.html') if m.group(2).endswith('.md') else m.group(2), m.group(1)), t)
    return unstash(t)
def flush():
    global para
    if para: out.append('<p>%s</p>' % inline(' '.join(para))); para = []
while i < len(src):
    l = src[i]
    if l.startswith('$$'):
        flush(); j = i + 1; buf = []
        while j < len(src) and not src[j].startswith('$$'): buf.append(src[j]); j += 1
        out.append('<div class="math">$$%s$$</div>' % html.escape('\n'.join(buf), quote=False)); i = j + 1; continue
    if l.startswith('<figure') or l.startswith('<svg'):
        # a raw HTML block runs to its closing </figure>
        flush(); j = i
        while j < len(src) and not src[j].startswith('</figure'): j += 1
        out.append('\n'.join(src[i:j + 1])); i = j + 1; continue
    if l.startswith('```'):
        flush(); j = i + 1; buf = []
        while j < len(src) and not src[j].startswith('```'): buf.append(src[j]); j += 1
        out.append('<pre>%s</pre>' % html.escape('\n'.join(buf))); i = j + 1; continue
    m = re.match(r'^(#{1,6})\s+(.*)$', l)
    if m:
        flush(); n = len(m.group(1)); text = m.group(2)
        anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
        out.append('<h%d id="%s">%s</h%d>' % (n, anchor, inline(text), n)); i += 1; continue
    if l.startswith('|'):
        flush(); rows = []
        while i < len(src) and src[i].startswith('|'):
            cells = [c.strip() for c in src[i].strip().strip('|').split('|')]
            if not all(re.match(r'^:?-+:?$', c) for c in cells): rows.append(cells)
            i += 1
        out.append('<table><tr>%s</tr>%s</table>' % (''.join('<th>%s</th>' % inline(c) for c in rows[0]),
                   ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % inline(c) for c in r) for r in rows[1:]))); continue
    if re.match(r'^\s*\d+\.\s+', l):
        flush(); items = []
        while i < len(src) and re.match(r'^\s*\d+\.\s+', src[i]):
            items.append(re.sub(r'^\s*\d+\.\s+', '', src[i])); i += 1
            while i < len(src) and src[i].startswith('   ') and not re.match(r'^\s*\d+\.\s+', src[i]): items[-1] += ' ' + src[i].strip(); i += 1
        out.append('<ol>%s</ol>' % ''.join('<li>%s</li>' % inline(t) for t in items)); continue
    m = re.match(r'^\s*[-*]\s+(.*)$', l)
    if m:
        flush(); items = []
        while i < len(src) and re.match(r'^\s*[-*]\s+', src[i]):
            items.append(re.sub(r'^\s*[-*]\s+', '', src[i])); i += 1
            while i < len(src) and src[i].startswith('  ') and not re.match(r'^\s*[-*]\s+', src[i]): items[-1] += ' ' + src[i].strip(); i += 1
        out.append('<ul>%s</ul>' % ''.join('<li>%s</li>' % inline(t) for t in items)); continue
    if not l.strip(): flush(); i += 1; continue
    para.append(l.strip()); i += 1
flush()
page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The probabilistic model · simmis city laboratory</title><link rel="stylesheet" href="/lab/lab.css">
<script>window.MathJax = {tex: {inlineMath: [["MJXBS(", "MJXBS)"]], displayMath: [["$$", "$$"]]}, svg: {fontCache: "global"}};</script>
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-svg.js"></script>
<style>.doc{max-width:880px;margin:0 auto;padding:28px 22px 80px}.doc h1{font-size:34px}.doc h2{margin-top:44px;border-top:1px solid var(--rail);padding-top:22px}.doc h3{font:15px var(--mono);margin-top:28px}
.doc p,.doc li{font-size:14px;line-height:1.7;color:var(--ink)}.doc pre{background:var(--sunken);border:1px solid var(--rail);padding:14px 16px;overflow:auto;font:12px/1.5 var(--mono);color:var(--ink)}
.doc code{font:12px var(--mono);color:var(--runtime-amber)}.doc table{border-collapse:collapse;width:100%;font-size:12px;margin:14px 0}.doc th,.doc td{padding:6px 8px;border-bottom:1px solid var(--rail);text-align:left;vertical-align:top}.doc th{color:var(--graphite);font-weight:normal}
.doc .back{font:11px var(--mono)}.doc .math{overflow-x:auto;margin:14px 0;color:var(--ink)}.doc figure{margin:24px 0;border:1px solid var(--rail);padding:12px}.doc figure > svg{width:100%;height:auto;display:block}.doc figcaption{font-size:12px;line-height:1.6;color:var(--graphite);margin-top:8px}.doc ol li{margin:6px 0}</style></head>
<body><header class="masthead"><a class="wordmark" href="https://simm.is">simm<span>is</span><i aria-hidden="true">▦</i></a><div class="project-name">city laboratory <span>/ the model</span></div>
<a class="stage" href="/lab.html">← BACK TO THE EXPLORER</a></header>
<main class="doc">{{BODY}}<p class="back hint">Rendered from <code>doc/model.md</code> in the repository; the chronological findings log is <code>doc/simulator.md</code>.</p></main></body></html>'''.replace('{{BODY}}', '\n'.join(out))
page = page.replace('MJXBS', chr(92) * 2)
open('public/model.html', 'w', encoding='utf-8').write(page)
print('public/model.html', len(page), 'bytes')
