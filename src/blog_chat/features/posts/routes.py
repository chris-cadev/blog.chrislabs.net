import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

from markupsafe import Markup

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse, Response, RedirectResponse

from blog_chat.core.filters import add_filter, add_markdown_filter
from blog_chat.core.ui import get_username_color
from blog_chat.core.i18n import (
    LANGS,
    language_switcher,
    make_t,
    preferred_lang,
    with_lang_cookie,
)
from blog_chat.core.logging import log_business_event
from blog_chat.core.responses import create_templates
from blog_chat.core.config import SITE_URL, UMAMI_ACTIVE, UMAMI_RECORDER_URL, UMAMI_SCRIPT_URL, UMAMI_WEBSITE_ID
import uuid as _uuid

from blog_chat.features.accounts.services import (
    create_token,
    generate_guest_name,
    get_username_from_cookie,
)
from blog_chat.features.posts.services import get_fb_post, get_fb_posts, get_post, get_post_by_lang_group, get_posts
from blog_chat.features.posts.schema import (
    article_schema,
    build_llms_txt,
    person_schema,
    to_jsonld,
    website_schema,
)

router = APIRouter()

posts_template_dirs = [
    Path("src/blog_chat/features/posts/templates"),
    Path("src/blog_chat/features/chat/templates"),
]
def _tag_class(tag: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")
    return slug or "unknown"


# Known slugs that already have a curated color in design/styles.css
KNOWN_TAG_SLUGS = {
    "life", "software", "meme", "joke", "laugh", "lol", "xd", "engineer",
    "christmas", "transition", "symbiotechnology", "adaptation", "work",
    "manufacturing", "project", "tool", "git", "github", "python", "inventor",
    "thought", "csharp", "dotnet", "think",
}

def _tag_hue(tag: str) -> int:
    # deterministic hash → hue 0-359 (stable across renders/processes)
    h = hashlib.md5(tag.lower().encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 360

def _tag_style(tag: str) -> Markup:
    slug = _tag_class(tag)
    if slug in KNOWN_TAG_SLUGS:
        return Markup("")
    hue = _tag_hue(tag)
    return Markup(f' style="--tag-h:{hue}"')


templates = create_templates(posts_template_dirs)
add_markdown_filter(templates)
add_filter(templates, "username_color", get_username_color)
add_filter(templates, "tag_class", _tag_class)
add_filter(templates, "tag_style", _tag_style)
add_filter(templates, "tag_hue", _tag_hue)
templates.env.globals["get_post_by_lang_group"] = get_post_by_lang_group

def _reading_time_aria(reading_time, lang="en"):
    if not isinstance(reading_time, dict):
        return ""
    try:
        from blog_chat.features.posts.reading_time import format_aria
        return format_aria(reading_time.get("minutes", 0), reading_time.get("seconds", 0), lang or "en")
    except Exception:
        return ""

add_filter(templates, "reading_time_aria", _reading_time_aria)

# OWASP ASVS 5.1.3 / Input Validation Cheat Sheet: positive (allowlist) validation
# Tags in content: letters (incl. accents), digits, hyphen, underscore, space, 1-64 chars.
# Rejects payloads like "{:tag}", "../", "<script>", "%2e", etc. before business logic.
_TAG_RE = re.compile(r"^[\w \-]{1,64}$", re.UNICODE)
PER_PAGE = 10


def _is_valid_tag(tag: str) -> bool:
    return bool(_TAG_RE.fullmatch(tag))


def _paginate(items: list, page: int, per_page: int = PER_PAGE) -> tuple[list, int, int]:
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], total_pages, page


def _index_list_ctx(request: Request, lang: str, page: int) -> dict:
    """Shared index list/pagination context for home and post-not-found."""
    all_posts = get_posts(lang)
    pinned_posts = [p for p in all_posts if p.get("pinned")][:3]
    pinned_slugs = {p["slug"] for p in pinned_posts}
    regular_posts = [p for p in all_posts if p["slug"] not in pinned_slugs]
    page_posts, total_pages, current_page = _paginate(regular_posts, page)
    chat_post = pinned_posts[0] if pinned_posts else (regular_posts[0] if regular_posts else None)
    return {
        "posts": page_posts,
        "pinned_posts": pinned_posts,
        "pinned_post": pinned_posts[0] if pinned_posts else None,
        "chat_post": chat_post,
        "room": chat_post["slug"] if chat_post else "offtopic",
        "page": current_page,
        "total_pages": total_pages,
        "total_posts": len(regular_posts),
        "language_switcher": language_switcher(request, lang, None),
    }


def _tags_data(lang: str):
    posts = get_posts(lang)
    counter: Counter = Counter()
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        for t in p.get("tags") or []:
            counter[t] += 1
            by_tag[t].append(p)
    tags_with_counts = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    posts_by_tag = {k: sorted(v, key=lambda x: str(x.get("created", "")), reverse=True) for k, v in by_tag.items()}
    posts_by_tag = {k: posts_by_tag[k] for k, _ in tags_with_counts}
    return tags_with_counts, posts_by_tag


def _render_tag_not_found(request: Request, lang: str) -> Response:
    tags_with_counts, posts_by_tag = _tags_data(lang)
    return _render(
        "tags.html",
        request,
        lang,
        status_code=404,
        apply_lang_cookie=False,
        tags_with_counts=tags_with_counts,
        posts_by_tag=posts_by_tag,
        is_tags_page=True,
        error=make_t(lang)("tag_not_found"),
        room="offtopic",
        slug=None,
        language_switcher=language_switcher(request, lang, None),
    )

CHAT_TOKEN_COOKIE = "chat_token"
CHAT_TOKEN_MAX_AGE = 60 * 60 * 24 * 30


def _render(
    template_name: str,
    request: Request,
    lang: str | None,
    status_code: int | None = None,
    apply_lang_cookie: bool = True,
    **extra,
) -> Response:
    username = get_username_from_cookie(request)
    generated = username is None
    if generated:
        username = generate_guest_name()
    extra["username"] = username

    template_kwargs = {}
    if status_code is not None:
        template_kwargs["status_code"] = status_code
    response = templates.TemplateResponse(
        request,
        template_name,
        context=_context(request, lang, **extra),
        **template_kwargs,
    )
    if apply_lang_cookie and lang in LANGS:
        response = with_lang_cookie(response, lang)
    if generated:
        guest_id = str(_uuid.uuid4())
        response.set_cookie(
            CHAT_TOKEN_COOKIE,
            create_token(guest_id, username),
            httponly=True,
            samesite="lax",
            path="/",
            max_age=CHAT_TOKEN_MAX_AGE,
        )
    return response


def resolve_theme_mode(cookies) -> str:
    raw = cookies.get("theme-mode")
    if raw in ("nord", "dark"):
        return "dark"
    if raw in ("nord-light", "light"):
        return "light"
    return "dark"


def _context(request: Request, lang: str | None, **extra) -> dict:
    theme_mode = resolve_theme_mode(request.cookies)
    ctx = {
        "request": request,
        "lang": lang,
        "t": make_t(lang),
        "theme_mode": theme_mode,
        "theme_data": "nord" if theme_mode == "dark" else "nord-light",
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    }
    ctx["umami"] = {
        "enabled": UMAMI_ACTIVE,
        "script_url": UMAMI_SCRIPT_URL,
        "recorder_url": UMAMI_RECORDER_URL,
        "website_id": UMAMI_WEBSITE_ID,
    }
    ctx["site_schema_json"] = to_jsonld(website_schema())
    if extra.get("post"):
        ctx["article_schema_json"] = to_jsonld(article_schema(extra["post"]))
    if extra.get("is_about_page"):
        ctx["person_schema_json"] = to_jsonld(person_schema(lang or "en"))
    ctx.update(extra)
    return ctx


def render_404(request: Request):
    lang = preferred_lang(request)
    username = get_username_from_cookie(request) or generate_guest_name()
    ctx = _context(request, lang, username=username)
    return templates.TemplateResponse(request, "404.html", context=ctx, status_code=404)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""


@router.get("/sitemap.xml", response_class=Response)
def sitemap(request: Request):
    posts = get_posts()
    urls = []
    for post in posts:
        lang = post.get("lang") or "en"
        date = post.get("updated") or post.get(
            "created") or datetime.now().isoformat()
        urls.append(f"""  <url>
    <loc>{SITE_URL}/{lang}/{post['slug']}</loc>
    <lastmod>{date}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
{chr(10).join(urls)}
</urlset>"""
    return Response(content=sitemap_xml, media_type="application/xml")


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    return build_llms_txt(get_posts())


@router.get("/about")
def about_redirect(request: Request):
    return RedirectResponse(f"/{preferred_lang(request)}/about", status_code=302)


@router.get("/{lang}/about")
def read_about(request: Request, lang: str):
    if lang not in LANGS:
        return RedirectResponse(f"/{preferred_lang(request)}/about", status_code=302)
    log_business_event("page.view", "About page viewed", lang=lang, path=f"/{lang}/about")
    return _render(
        "about.html",
        request,
        lang,
        slug=None,
        is_about_page=True,
        room="offtopic",
        language_switcher=language_switcher(request, lang, "about"),
    )


@router.get("/")
def read_root(request: Request):
    lang = preferred_lang(request)
    return RedirectResponse(f"/{lang}/", status_code=302)


@router.get("/{lang}/")
def read_lang_index(request: Request, lang: str, page: int = Query(1, ge=1)):
    if lang not in LANGS:
        return _render(
            "index.html",
            request,
            "en",
            status_code=404,
            apply_lang_cookie=False,
            posts=get_posts(),
            error=make_t("en")("language_not_found"),
            slug=None,
            page=1,
            total_pages=1,
            language_switcher=language_switcher(request, None, None),
        )
    log_business_event("page.view", "Blog index viewed", lang=lang, path=f"/{lang}/")
    is_htmx = request.headers.get("HX-Request")
    ctx = _index_list_ctx(request, lang, page)
    return _render(
        "_posts_page.html" if is_htmx else "index.html",
        request,
        lang,
        slug=None,
        **ctx,
    )


@router.get("/tags/{tag}")
def read_tag_redirect(request: Request, tag: str):
    if not _is_valid_tag(tag):
        # fail-closed: malformed tags never reach lookup; show tags overview with tag_not_found
        return _render_tag_not_found(request, preferred_lang(request))
    return RedirectResponse(f"/{preferred_lang(request)}/tags/{tag}")


@router.get("/{lang}/tags/{tag}")
def read_tag(request: Request, lang: str, tag: str, page: int = Query(1, ge=1)):
    if lang not in LANGS:
        return RedirectResponse(f"/{preferred_lang(request)}/tags/{tag}")
    if not _is_valid_tag(tag):
        return _render_tag_not_found(request, lang)
    all_posts = [p for p in get_posts(lang) if tag in (p.get("tags") or [])]
    if not all_posts:
        return _render_tag_not_found(request, lang)
    page_posts, total_pages, current_page = _paginate(all_posts, page)
    log_business_event(
        "page.view",
        "Tag page viewed",
        lang=lang,
        tag=tag,
        path=f"/{lang}/tags/{tag}",
    )
    is_htmx = request.headers.get("HX-Request")
    return _render(
        "_posts_page.html" if is_htmx else "index.html",
        request,
        lang,
        posts=page_posts,
        tag=tag,
        room="offtopic",
        slug=None,
        page=current_page,
        total_pages=total_pages,
        total_posts=len(all_posts),
        language_switcher=language_switcher(request, lang, None),
    )


@router.get("/{lang}/tags")
def read_tags(request: Request, lang: str):
    if lang not in LANGS:
        return RedirectResponse(f"/{preferred_lang(request)}/tags")
    tags_with_counts, posts_by_tag = _tags_data(lang)
    log_business_event("page.view", "Tags overview viewed", lang=lang, path=f"/{lang}/tags")
    return _render(
        "tags.html",
        request,
        lang,
        tags_with_counts=tags_with_counts,
        posts_by_tag=posts_by_tag,
        is_tags_page=True,
        room="offtopic",
        slug=None,
        language_switcher=language_switcher(request, lang, None),
    )


def _post_not_found(request: Request, lang: str, slug: str | None, page: int) -> Response:
    is_htmx = request.headers.get("HX-Request")
    ctx = _index_list_ctx(request, lang, page)
    # HTMX partials: 200 so hx-swap/hx-push-url work; full page keeps 404.
    return _render(
        "_posts_page.html" if is_htmx else "index.html",
        request,
        lang,
        status_code=None if is_htmx else 404,
        apply_lang_cookie=lang in LANGS,
        error=make_t(lang)("post_not_found"),
        slug=slug,
        **ctx,
    )


@router.get("/{lang}/fb/{slug:path}")
def read_fb_item(request: Request, lang: str, slug: str, page: int = Query(1, ge=1)):
    if lang not in LANGS:
        return _post_not_found(request, "en", None, page)
    post = get_fb_post(slug)
    if not post:
        return _post_not_found(request, lang, slug, page)
    log_business_event(
        "page.view",
        "FB post viewed",
        lang=lang,
        slug=slug,
        path=request.url.path,
    )
    return _render(
        "post.html",
        request,
        lang,
        post=post,
        room=slug,
        slug=slug,
        language_switcher=language_switcher(request, lang, f"fb/{slug}"),
    )


@router.get("/{lang}/{slug:path}")
def read_item(request: Request, lang: str, slug: str, page: int = Query(1, ge=1)):
    if lang not in LANGS:
        legacy = get_post(f"{lang}/{slug}")
        if legacy:
            legacy_lang = legacy.get("lang") or "en"
            return _render(
                "post.html",
                request,
                legacy_lang,
                post=legacy,
                room=legacy.get("slug"),
                slug=legacy.get("slug"),
                language_switcher=language_switcher(request, legacy_lang, legacy.get("slug")),
            )
        return _post_not_found(request, "en", None, page)
    post = get_post(slug, lang)
    if not post:
        return _post_not_found(request, lang, slug, page)
    log_business_event(
        "page.view",
        "Post viewed",
        lang=lang,
        slug=slug,
        path=request.url.path,
    )
    return _render(
        "post.html",
        request,
        lang,
        post=post,
        room=slug,
        slug=slug,
        language_switcher=language_switcher(request, lang, slug),
    )
