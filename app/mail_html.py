"""HTML emails: one layout for every email the server sends - account emails (verify,
reset, sign-up attempts, the SMTP test) and the email notification channel.

Email clients ignore stylesheets and most modern CSS, so the layout is a single-column
table with inline styles: a header band with the shop's name, a card with a heading,
paragraphs, an optional button (and its link spelled out for clients that block it),
optional rows of games with their covers, and a footer. Every text is escaped; the
plain-text version of each email still goes along for clients that show text only.
"""
from html import escape

ACCENT = '#00b8a6'
TEXT = '#1f2328'
MUTED = '#59636e'
PAGE = '#eef1f4'


def _p(text, style=''):
    return (f'<p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:{TEXT};{style}">'
            f'{escape(text).replace(chr(10), "<br>")}</p>')


def render(shop, heading, paragraphs, button=None, fallback=None, items=None, footer=None, note=None):
    """The whole email as an HTML document.
      paragraphs  plain texts, one <p> each
      button      (label, url): a call to action; `fallback` introduces the bare link
      items       [{'text': ..., 'image': url or None, 'sub': ...}]: rows with a cover
      note        a muted line under the button ("if you didn't ask for this...")"""
    body = [f'<h1 style="margin:0 0 16px;font-size:21px;line-height:1.3;color:{TEXT};">{escape(heading)}</h1>']
    body += [_p(p) for p in paragraphs if p]
    if items:
        rows = []
        for item in items:
            image = item.get('image')
            cover = (f'<img src="{escape(image, quote=True)}" width="56" height="56" alt="" '
                     f'style="display:block;width:56px;height:56px;border-radius:10px;object-fit:cover;">'
                     if image else
                     f'<div style="width:56px;height:56px;border-radius:10px;background:{PAGE};"></div>')
            sub = (f'<div style="font-size:13px;color:{MUTED};margin-top:2px;">{escape(item["sub"])}</div>'
                   if item.get('sub') else '')
            rows.append(
                f'<tr><td style="padding:8px 12px 8px 0;width:56px;vertical-align:middle;">{cover}</td>'
                f'<td style="padding:8px 0;vertical-align:middle;font-size:15px;color:{TEXT};">'
                f'{escape(item["text"])}{sub}</td></tr>')
        body.append('<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
                    f'style="width:100%;margin:4px 0 14px;border-top:1px solid {PAGE};">{"".join(rows)}</table>')
    if button:
        label, url = button
        body.append(
            '<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:8px 0 18px;">'
            f'<tr><td style="border-radius:10px;background:{ACCENT};">'
            f'<a href="{escape(url, quote=True)}" style="display:inline-block;padding:12px 22px;font-size:15px;'
            f'font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px;">{escape(label)}</a>'
            '</td></tr></table>')
        if fallback:
            body.append(f'<p style="margin:0 0 14px;font-size:13px;line-height:1.5;color:{MUTED};">'
                        f'{escape(fallback)}<br><a href="{escape(url, quote=True)}" '
                        f'style="color:{ACCENT};word-break:break-all;">{escape(url)}</a></p>')
    if note:
        body.append(_p(note, f'color:{MUTED};font-size:13px;'))
    foot = f'<p style="margin:16px 0 0;font-size:12px;color:{MUTED};text-align:center;">{escape(footer)}</p>' \
        if footer else ''
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="margin:0;padding:0;background:{PAGE};font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:{PAGE};">'
        '<tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:560px;">'
        f'<tr><td style="padding:18px 24px;border-radius:14px 14px 0 0;background:#0d1117;'
        f'background-image:linear-gradient(120deg,#0d1117 0%,#123a3a 60%,{ACCENT} 140%);">'
        f'<span style="font-size:18px;font-weight:700;color:#ffffff;letter-spacing:.2px;">{escape(shop)}</span>'
        '</td></tr>'
        f'<tr><td style="padding:26px 24px 12px;background:#ffffff;border-radius:0 0 14px 14px;">{"".join(body)}</td></tr>'
        f'<tr><td>{foot}</td></tr>'
        '</table></td></tr></table></body></html>')


def from_text(shop, heading, body, link, button_label, fallback, footer):
    """An account email's HTML from its plain-text body: each paragraph a <p>, and the
    paragraph that holds the link becomes its lead-in plus a button. The plain text
    stays the source of truth (it is what the translations hold)."""
    marker = '\x00LINK\x00'
    text = body.replace(link, marker) if link else body
    paragraphs, button, note = [], None, None
    after = False
    for para in text.split('\n\n'):
        if marker in para:
            lead = para.replace(marker, '').strip().rstrip(':').strip()
            if lead:
                paragraphs.append(lead + '.' if not lead.endswith(('.', ')', '!')) else lead)
            button = (button_label, link)
            after = True
        elif after:
            note = (note + '\n\n' if note else '') + para.strip()
        else:
            paragraphs.append(para.strip())
    return render(shop, heading, paragraphs, button=button, fallback=fallback if button else None,
                  footer=footer, note=note)
