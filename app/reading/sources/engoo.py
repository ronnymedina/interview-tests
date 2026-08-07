"""Único lugar del proyecto que conoce Engoo.

Todo lo frágil vive acá: las URLs, el User-Agent especial y el parseo del HTML. Si Engoo
cambia su markup, este archivo es lo único que se toca, y mientras tanto el catálogo ya
guardado sigue sirviendo — una ruptura degrada a "textos viejos", no a "feature caída".

## Cómo se obtiene el HTML

Engoo es una SPA: con un User-Agent normal devuelve solo el shell vacío. El HTML renderizado
aparece únicamente al declararse Googlebot (`settings.READING_USER_AGENT`). Funciona hoy y su
`robots.txt` no lo prohíbe — el `Disallow:` está vacío y solo bloquea `/tutors?`,
`/app/oauth/` y `/sales` — pero es un comportamiento no documentado que puede cambiar.

## Por qué se parsea así

Las clases son hashes de Emotion, que cambian cuando Engoo despliega. Hoy el cuerpo del
artículo vive dentro de un `div.css-19m2fbm`, y usarlo da un resultado exacto: título y
párrafos, sin el menú ni el bloque de vocabulario. Pero apostar todo a un hash es apostar a
que no despliegan.

Por eso hay dos estrategias: se intenta el selector, y si no encuentra nada se cae a una
heurística que no depende de ninguna clase (ver `_body_by_heuristic`). El fallback deja un
warning en el log, que es la señal de que hay que actualizar el selector.

En el listado no hay ni siquiera esa opción: el orden de los campos de una tarjeta varía
entre el índice y las categorías, con un "New" opcional adelante. Así que de ahí se saca
solo lo mínimo estable — la URL y el nivel, único token que es un entero suelto — y el
resto sale de la página del artículo.
"""

import asyncio
import re
from itertools import zip_longest

import httpx
import structlog
from bs4 import BeautifulSoup, Tag

from app.reading.model import ReadingText
from config import settings

logger = structlog.get_logger(__name__)

_BASE = "https://engoo.com"
_SOURCE_NAME = "engoo"

# Las cinco categorías de Daily News. El identificador opaco es parte de la URL y no se
# puede derivar del slug, así que va escrito. Se pagina por categoría: el índice general
# ignora `?page=`, las categorías no.
_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Business & Politics", "/app/daily-news/category/business-politics/g422El24T2-cp4ZD5C3oeQ"),
    ("Science & Technology", "/app/daily-news/category/science-technology/NsA7ULu6SB-n5NKynT-kfA"),
    ("Health & Lifestyle", "/app/daily-news/category/health-lifestyle/gFMVmUuNQ7atEeS09YtzZQ"),
    ("Culture & Society", "/app/daily-news/category/culture-society/GmM-aNukTLqFeqncqCuSwQ"),
    ("Travel & Experiences", "/app/daily-news/category/travel-experiences/BvsrQV68TciuqXebtgwiJA"),
)

# Contenedor del artículo. Hash de Emotion: se espera que caduque, de ahí el fallback.
_BODY_SELECTOR = "div.css-19m2fbm"

_ARTICLE_PATH = re.compile(r"^/app/daily-news/article/")
_TITLE_SUFFIX = " | Engoo Daily News"
# Título de la página cuando Engoo devuelve el shell de la SPA en vez del HTML renderizado.
_SHELL_TITLE = "Engoo"

# Un artículo que no renderizó se reintenta una vez. La SSR de Engoo falla de a ratos y el
# reintento casi siempre lo recupera; sin él se perderían artículos al azar en cada corrida.
_ARTICLE_RETRIES = 1
_RETRY_DELAY_SECONDS = 2.0
# "August 05, 2026" — queda como texto tal cual lo publica la fuente; no se normaliza a
# date porque no se filtra ni ordena por ella, solo se muestra.
_PUBLISHED = re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b")
# Nivel: un entero de 1 o 2 dígitos que ocupa un nodo de texto completo.
_LEVEL_TOKEN = re.compile(r"^\d{1,2}$")

# El chrome de navegación llega al HTML como enlaces concatenados sin espacios
# ("NewsCategoryAllBusiness & Politics..."), lo que produce tokens larguísimos. Ninguna
# palabra inglesa real se acerca a este largo, así que sirve para separar el menú del
# artículo sin depender de ninguna clase.
_MAX_REAL_WORD = 25

# Pie de cada lección; no es parte del texto que se lee en voz alta.
_ATTRIBUTION = re.compile(r"^This lesson is based on an article by\b", re.I)

# Un resto más corto que esto es una migaja del menú, no un párrafo de verdad.
_MIN_LEAD_WORDS = 10


def _text_of(node: Tag) -> str:
    """Texto visible de un nodo, con separador entre etiquetas anidadas.

    El separador importa: sin él, `<p>Texto con <b>negrita</b> acá</p>` sale con las
    palabras pegadas ("connegrita"), que después Azure evaluaría como una palabra inexistente.
    """
    return node.get_text(" ", strip=True)


def _parse_listing(page_html: str) -> list[tuple[str, int | None]]:
    """Saca (url_absoluta, nivel) de cada tarjeta del listado, sin repetir.

    El nivel puede venir None: "no conozco el nivel" y "nivel 0" son cosas distintas, y la
    columna es nullable justamente para no inventar un cero.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    found: dict[str, int | None] = {}
    for anchor in soup.find_all("a", href=_ARTICLE_PATH):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = _BASE + href
        if url in found:
            continue
        level = next(
            (
                int(chunk)
                for chunk in anchor.stripped_strings
                if _LEVEL_TOKEN.match(chunk)
            ),
            None,
        )
        found[url] = level
    return list(found.items())


def _body_by_selector(soup: BeautifulSoup) -> list[str]:
    """Párrafos del contenedor del artículo. Lista vacía si el selector ya no existe."""
    container = soup.select_one(_BODY_SELECTOR)
    if container is None:
        return []
    return [
        text
        for text in (_text_of(p) for p in container.find_all("p") if isinstance(p, Tag))
        if text and not _ATTRIBUTION.match(text)
    ]


def _body_by_heuristic(soup: BeautifulSoup, title: str) -> list[str]:
    """Fallback sin selectores: separa artículo de chrome por el largo de los tokens.

    El primer párrafo real viene pegado al final del bloque de navegación y vocabulario,
    justo después de una repetición del título; se lo rescata cortando por esa última
    aparición del título.
    """
    body: list[str] = []
    for para in (_text_of(p) for p in soup.find_all("p") if isinstance(p, Tag)):
        if not para or _ATTRIBUTION.match(para):
            continue
        if max((len(tok) for tok in para.split()), default=0) <= _MAX_REAL_WORD:
            body.append(para)
            continue
        cut = para.rfind(title)
        if cut != -1:
            lead = para[cut + len(title) :].strip()
            if len(lead.split()) >= _MIN_LEAD_WORDS:
                body.insert(0, lead)
    return body


def _parse_article(page_html: str, url: str) -> tuple[str, str, str] | None:
    """Devuelve (título, cuerpo, fecha) de la página de un artículo, o None si no se pudo."""
    soup = BeautifulSoup(page_html, "html.parser")

    if soup.title is None or not soup.title.string:
        return None
    title = soup.title.string.strip().removesuffix(_TITLE_SUFFIX).strip()
    # Sin párrafos y con el título genérico, lo que llegó es el shell vacío de la SPA: Engoo
    # a veces no renderiza del lado del servidor. No es un problema de parseo y no merece
    # warning acá — quien llama reintenta.
    if not title or title == _SHELL_TITLE or not soup.find("p"):
        return None

    body = _body_by_selector(soup)
    if not body:
        logger.warning(
            "selector_caducado",
            detalle="No encontró el cuerpo; se usa la heurística. "
            "Probablemente Engoo desplegó y cambió el hash de la clase.",
            selector=_BODY_SELECTOR,
            url=url,
        )
        body = _body_by_heuristic(soup, title)
    if not body:
        return None

    published_match = _PUBLISHED.search(soup.get_text(" ", strip=True))
    published = published_match.group(1) if published_match else ""

    return title, "\n\n".join(body), published


class EngooSource:
    """Fuente Engoo Daily News. Implementa `ReadingSource`.

    Recorre las categorías con el filtro de nivel en la URL y baja cada artículo. Un
    artículo que falla se omite con un warning: una nota rota no puede tumbar la corrida.
    """

    def __init__(
        self,
        *,
        min_level: int | None = None,
        max_level: int | None = None,
        pages_per_category: int | None = None,
        max_articles: int | None = None,
    ) -> None:
        self._min_level = settings.READING_MIN_LEVEL if min_level is None else min_level
        self._max_level = settings.READING_MAX_LEVEL if max_level is None else max_level
        self._pages = (
            settings.READING_INGEST_PAGES if pages_per_category is None else pages_per_category
        )
        self._max_articles = (
            settings.READING_INGEST_MAX_ARTICLES if max_articles is None else max_articles
        )

    @property
    def name(self) -> str:
        return _SOURCE_NAME

    async def fetch(self) -> list[ReadingText]:
        headers = {"User-Agent": settings.READING_USER_AGENT}
        timeout = httpx.Timeout(settings.READING_HTTP_TIMEOUT_SECONDS)
        # follow_redirects: Engoo responde 302 a la URL canónica cuando los parámetros de
        # la query vienen en otro orden. httpx no las sigue por defecto.
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True
        ) as client:
            listings = await self._collect_listings(client)
            if not listings:
                # Ni un enlace en ninguna categoría no es "no hay nada nuevo": es que el
                # HTML cambió o nos bloquearon. Que reviente, para que se vea en el log.
                raise RuntimeError(
                    "Engoo no devolvió ningún artículo: ¿cambió el HTML o el User-Agent?"
                )
            return await self._fetch_articles(client, listings)

    async def _collect_listings(
        self, client: httpx.AsyncClient
    ) -> list[tuple[str, int | None, str]]:
        """Recorre categorías y páginas. Devuelve (url, nivel, categoría) sin duplicados.

        Las categorías van en secuencia a propósito: son cinco, y no vale la pena golpear el
        sitio en paralelo por ellas. La paginación de una categoría corta en cuanto una
        página no trae artículos, que es como la fuente indica que se agotó.

        El resultado sale intercalado entre categorías, no concatenado. Importa porque el
        tope de artículos por corrida se aplica después, cortando la lista: concatenadas, las
        primeras categorías se comerían toda la cuota y el catálogo quedaría sesgado a un par
        de temas. Intercaladas, el recorte se reparte parejo.
        """
        seen: set[str] = set()
        by_category: list[list[tuple[str, int | None, str]]] = []
        for category, path in _CATEGORIES:
            found: list[tuple[str, int | None, str]] = []
            for page in range(1, self._pages + 1):
                params = {
                    "min_level": self._min_level,
                    "max_level": self._max_level,
                    "page": page,
                }
                try:
                    response = await client.get(_BASE + path, params=params)
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.warning("listado_fallido", category=category, page=page)
                    break
                entries = _parse_listing(response.text)
                if not entries:
                    break
                for url, level in entries:
                    if url not in seen:
                        seen.add(url)
                        found.append((url, level, category))
            by_category.append(found)

        return [
            entry
            for group in zip_longest(*by_category)
            for entry in group
            if entry is not None
        ]

    async def _fetch_articles(
        self, client: httpx.AsyncClient, listings: list[tuple[str, int | None, str]]
    ) -> list[ReadingText]:
        """Baja los artículos con concurrencia acotada y arma los ReadingText."""
        limited = listings[: self._max_articles]
        semaphore = asyncio.Semaphore(settings.READING_INGEST_CONCURRENCY)

        async def one(url: str, level: int | None, category: str) -> ReadingText | None:
            parsed = None
            for attempt in range(_ARTICLE_RETRIES + 1):
                if attempt:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)
                async with semaphore:
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                    except httpx.HTTPError:
                        logger.warning("descarga_fallida", url=url)
                        return None
                parsed = _parse_article(response.text, url)
                if parsed is not None:
                    break
            if parsed is None:
                logger.warning(
                    "articulo_sin_contenido",
                    detalle="La fuente devolvió el shell vacío de la SPA; se omite.",
                    url=url,
                    intentos=_ARTICLE_RETRIES + 1,
                )
                return None
            title, body, published = parsed
            return ReadingText(
                source=_SOURCE_NAME,
                source_url=url,
                title=title,
                body=body,
                level=level,
                category=category,
                published_at=published,
            )

        results = await asyncio.gather(*(one(u, lv, c) for u, lv, c in limited))
        return [text for text in results if text is not None]
