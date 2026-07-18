"""Query API trên registry.db — interface chính cho pipeline P1."""
import sqlite3
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process


@dataclass
class ProductHit:
    product_id: int
    trade_name: str
    formulation: str | None
    active_ingredient: str
    registrant: str | None
    status: str
    cite: str
    source_url: str = ""


@dataclass
class Resolution:
    canonical: str
    ambiguous: bool
    score: float


def connect(path: str = "data/registry.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().lower()


def _cite(row) -> str:
    return f"Phụ lục Thông tư {row['so_hieu']} (hiệu lực từ {row['effective_from']})"


_BASE = """SELECT p.id AS product_id, p.trade_name, p.formulation, p.registrant, p.status,
                  ai.name_common AS active_ingredient, d.so_hieu, d.url AS source_url,
                  p.effective_from, p.effective_to
           FROM products p
           JOIN active_ingredients ai ON ai.id = p.ai_id
           JOIN docs d ON d.id = p.doc_id"""

_DATE = " p.effective_from <= :d AND (p.effective_to IS NULL OR p.effective_to > :d)"


def _hit(row) -> ProductHit:
    return ProductHit(
        product_id=row["product_id"],
        trade_name=row["trade_name"],
        formulation=row["formulation"],
        active_ingredient=row["active_ingredient"],
        registrant=row["registrant"],
        status=row["status"],
        cite=_cite(row),
        source_url=row["source_url"],
    )


def lookup_products(conn, crop: str, pest: str, on_date: str) -> list[ProductHit]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        _BASE + " JOIN uses u ON u.product_id = p.id"
                " WHERE u.crop = :crop AND u.pest = :pest AND p.status = 'allowed' AND" + _DATE +
                " ORDER BY p.trade_name",
        {"crop": _norm(crop), "pest": _norm(pest), "d": on_date}).fetchall()
    return [_hit(r) for r in rows]


def lookup_exact_products(
    conn: sqlite3.Connection,
    trade_name: str,
    formulation: str | None,
    on_date: str,
) -> list[ProductHit]:
    """Return current exact product identities; never fuzzy-match tool arguments."""
    conn.row_factory = sqlite3.Row
    query = _BASE + " WHERE p.trade_name = :trade COLLATE NOCASE AND" + _DATE
    params = {"trade": trade_name.strip(), "d": on_date}
    if formulation is not None:
        query += " AND ifnull(p.formulation, '') = :formulation COLLATE NOCASE"
        params["formulation"] = formulation.strip()
    query += " ORDER BY p.trade_name, p.formulation, p.effective_from DESC"
    return [_hit(row) for row in conn.execute(query, params).fetchall()]


def get_product_hit(conn: sqlite3.Connection, product_id: int) -> ProductHit | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(_BASE + " WHERE p.id = ? LIMIT 1", (product_id,)).fetchone()
    return _hit(row) if row is not None else None


def product_has_registered_use(
    conn: sqlite3.Connection,
    product_id: int,
    crop: str,
    pest: str,
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM uses
           WHERE product_id=? AND crop=? COLLATE NOCASE AND pest=? COLLATE NOCASE
           LIMIT 1""",
        (product_id, _norm(crop), _norm(pest)),
    ).fetchone()
    return row is not None


def list_product_uses(conn: sqlite3.Connection, product_id: int) -> list[tuple[str, str]]:
    rows = conn.execute(
        """SELECT DISTINCT crop, pest FROM uses
           WHERE product_id=? ORDER BY crop, pest""",
        (product_id,),
    ).fetchall()
    return [(row["crop"], row["pest"]) for row in rows]


def check_product_status(conn, name: str, on_date: str) -> ProductHit | None:
    """Tra trạng thái theo tên thương phẩm, chấp nhận gõ/nghe sai nhẹ (fuzzy ≥ 85)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(_BASE + " WHERE " + _DATE, {"d": on_date}).fetchall()
    if not rows:
        return None
    names = {i: f"{r['trade_name']} {r['formulation'] or ''}".strip().lower() for i, r in enumerate(rows)}
    best = process.extractOne(_norm(name), names, scorer=fuzz.WRatio, score_cutoff=85)
    if not best:
        return None
    return _hit(rows[best[2]])


def resolve_alias(conn, text: str, entity_type: str) -> Resolution | None:
    conn.row_factory = sqlite3.Row
    t = _norm(text)
    row = conn.execute("SELECT canonical, ambiguous FROM aliases WHERE entity_type=? AND alias=?",
                       (entity_type, t)).fetchone()
    if row:
        return Resolution(row["canonical"], bool(row["ambiguous"]), 100.0)
    rows = conn.execute("SELECT canonical, ambiguous, alias FROM aliases WHERE entity_type=?",
                        (entity_type,)).fetchall()
    if not rows:
        return None
    choices = {i: r["alias"] for i, r in enumerate(rows)}
    best = process.extractOne(t, choices, scorer=fuzz.WRatio, score_cutoff=88)
    if not best:
        return None
    r = rows[best[2]]
    return Resolution(r["canonical"], bool(r["ambiguous"]), float(best[1]))


@dataclass
class LabelDose:
    product_trade_name: str
    formulation: str | None
    crop: str
    pest: str
    dose_text: str
    water_text: str | None
    phi_days: int | None
    method: str | None
    source_url: str


def connect_labels(path: str = "data/labels.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_dose(lconn, trade_name: str, crop: str, pest: str, formulation: str | None = None) -> LabelDose | None:
    """Liều CHỈ hợp lệ cho đúng quy cách (formulation): cùng tên thương mại nhưng
    5SC vs 20WP là nồng độ khác nhau, liều khác nhau — tra thiếu formulation từng
    gây hiển thị liều 20WP cho sản phẩm 3SL (bug thật, 2026-07-18)."""
    row = lconn.execute(
        """SELECT * FROM label_doses WHERE verified=1 AND entry_pass=1
           AND lower(product_trade_name)=? AND crop=? AND pest=?
           AND lower(ifnull(formulation,'')) = lower(ifnull(?, '')) LIMIT 1""",
        (trade_name.strip().lower(), crop.strip().lower(), pest.strip().lower(),
         (formulation or "").strip())).fetchone()
    if not row:
        return None
    return LabelDose(row["product_trade_name"], row["formulation"], row["crop"], row["pest"],
                     row["dose_text"], row["water_text"], row["phi_days"], row["method"], row["source_url"])


def get_verified_doses(lconn, crop: str, pest: str) -> dict[tuple[str, str], LabelDose]:
    """Load every verified dose for one crop/pest pair in a single query."""
    rows = lconn.execute(
        """SELECT * FROM label_doses WHERE verified=1 AND entry_pass=1
           AND crop=? AND pest=? ORDER BY product_trade_name, formulation""",
        (crop.strip().lower(), pest.strip().lower()),
    ).fetchall()
    doses: dict[tuple[str, str], LabelDose] = {}
    for row in rows:
        key = (
            row["product_trade_name"].strip().casefold(),
            (row["formulation"] or "").strip().casefold(),
        )
        doses[key] = LabelDose(
            row["product_trade_name"], row["formulation"], row["crop"], row["pest"],
            row["dose_text"], row["water_text"], row["phi_days"], row["method"], row["source_url"],
        )
    return doses
