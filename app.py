"""
Negocito POS — Prototipo funcional
Punto de venta ligero para micronegocios en Puerto Rico: inventario,
ventas con cálculo automático de IVU (11.5%), reportes, y un flujo
simulado de cobro vía "ATH Móvil" (mock — en producción se conectaría
a la API real de ATH Business en vez de competir con ella).
"""
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

APP_DIR = Path(__file__).parent
# DB_DIR permite montar un volumen de Docker (o cualquier disco persistente)
# separado del código, para que los datos sobrevivan a un rebuild/redeploy.
DB_DIR = Path(os.environ.get("DB_DIR", APP_DIR))
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "negocito.db"
IVU_RATE = 0.115  # 11.5% (10.5% estatal + 1% municipal), vigente 2026

app = Flask(__name__)


# ---------------------------------------------------------------- DB setup
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            subtotal REAL NOT NULL,
            ivu REAL NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            ath_reference TEXT
        );

        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id),
            product_id INTEGER,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            line_total REAL NOT NULL
        );
        """
    )
    db.commit()

    # Seed de ejemplo si la tabla de productos está vacía
    cur = db.execute("SELECT COUNT(*) AS c FROM products")
    if cur.fetchone()["c"] == 0:
        now = datetime.utcnow().isoformat()
        db.executemany(
            "INSERT INTO products (name, category, price, stock, low_stock_threshold, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Café con leche", "Bebidas", 3.50, 40, 10, now),
                ("Pastelillo de guayaba", "Panadería", 2.25, 25, 8, now),
                ("Agua 16oz", "Bebidas", 1.50, 60, 15, now),
                ("Empanada de pollo", "Comida", 3.00, 4, 6, now),
            ],
        )
        db.commit()
    db.close()


# ------------------------------------------------------------------ Pages
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------- Productos
@app.route("/api/products", methods=["GET"])
def list_products():
    db = get_db()
    rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    price = data.get("price")
    stock = data.get("stock", 0)
    category = data.get("category") or "General"
    threshold = data.get("low_stock_threshold", 5)

    if not name or price is None:
        return jsonify({"error": "Nombre y precio son requeridos"}), 400
    try:
        price = float(price)
        stock = int(stock)
        threshold = int(threshold)
    except (TypeError, ValueError):
        return jsonify({"error": "Precio, cantidad y umbral deben ser numéricos"}), 400
    if price < 0 or stock < 0:
        return jsonify({"error": "Precio y cantidad no pueden ser negativos"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO products (name, category, price, stock, low_stock_threshold, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, category, price, stock, threshold, datetime.utcnow().isoformat()),
    )
    db.commit()
    row = db.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    data = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Producto no encontrado"}), 404

    name = data.get("name", row["name"])
    category = data.get("category", row["category"])
    try:
        price = float(data.get("price", row["price"]))
        stock = int(data.get("stock", row["stock"]))
        threshold = int(data.get("low_stock_threshold", row["low_stock_threshold"]))
    except (TypeError, ValueError):
        return jsonify({"error": "Valores numéricos inválidos"}), 400

    db.execute(
        "UPDATE products SET name=?, category=?, price=?, stock=?, low_stock_threshold=? WHERE id=?",
        (name, category, price, stock, threshold, product_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return jsonify(dict(updated))


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ Venta
@app.route("/api/sales", methods=["POST"])
def create_sale():
    data = request.get_json(force=True)
    items = data.get("items") or []
    payment_method = data.get("payment_method", "efectivo")

    if not items:
        return jsonify({"error": "La venta necesita al menos un producto"}), 400

    db = get_db()
    subtotal = 0.0
    resolved_items = []

    for it in items:
        pid = it.get("product_id")
        qty = it.get("quantity")
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            return jsonify({"error": "Cantidad inválida"}), 400
        if qty <= 0:
            return jsonify({"error": "Cantidad debe ser mayor a cero"}), 400

        product = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if product is None:
            return jsonify({"error": f"Producto {pid} no existe"}), 400
        if product["stock"] < qty:
            return jsonify(
                {"error": f'No hay suficiente inventario de "{product["name"]}" (disponible: {product["stock"]})'}
            ), 400

        line_total = round(product["price"] * qty, 2)
        subtotal += line_total
        resolved_items.append(
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "quantity": qty,
                "unit_price": product["price"],
                "line_total": line_total,
            }
        )

    subtotal = round(subtotal, 2)
    ivu = round(subtotal * IVU_RATE, 2)
    total = round(subtotal + ivu, 2)

    # --- Simulación de cobro ATH Móvil ---
    # En producción esto llamaría a la API real de ATH Business para generar
    # el cobro (pATH) y confirmar el pago. Aquí generamos una referencia mock
    # para demostrar el flujo sin credenciales reales.
    ath_reference = None
    if payment_method == "ath_movil":
        ath_reference = f"ATH-SIM-{uuid.uuid4().hex[:8].upper()}"

    now = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO sales (created_at, subtotal, ivu, total, payment_method, ath_reference) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (now, subtotal, ivu, total, payment_method, ath_reference),
    )
    sale_id = cur.lastrowid

    for it in resolved_items:
        db.execute(
            "INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, line_total) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sale_id, it["product_id"], it["product_name"], it["quantity"], it["unit_price"], it["line_total"]),
        )
        db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (it["quantity"], it["product_id"]))

    db.commit()

    return jsonify(
        {
            "id": sale_id,
            "created_at": now,
            "items": resolved_items,
            "subtotal": subtotal,
            "ivu": ivu,
            "ivu_rate": IVU_RATE,
            "total": total,
            "payment_method": payment_method,
            "ath_reference": ath_reference,
        }
    ), 201


@app.route("/api/sales", methods=["GET"])
def list_sales():
    db = get_db()
    limit = int(request.args.get("limit", 20))
    rows = db.execute(
        "SELECT * FROM sales ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    sales = []
    for r in rows:
        sale = dict(r)
        items = db.execute(
            "SELECT product_name, quantity, unit_price, line_total FROM sale_items WHERE sale_id = ?",
            (r["id"],),
        ).fetchall()
        sale["items"] = [dict(i) for i in items]
        sales.append(sale)
    return jsonify(sales)


# --------------------------------------------------------------- Reportes
def _period_start(period: str) -> str:
    now = datetime.utcnow()
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:  # today
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


@app.route("/api/reports/summary", methods=["GET"])
def report_summary():
    period = request.args.get("period", "today")
    start = _period_start(period)
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(subtotal),0) AS subtotal, "
        "COALESCE(SUM(ivu),0) AS ivu, COALESCE(SUM(total),0) AS total "
        "FROM sales WHERE created_at >= ?",
        (start,),
    ).fetchone()

    by_method = db.execute(
        "SELECT payment_method, COUNT(*) AS count, COALESCE(SUM(total),0) AS total "
        "FROM sales WHERE created_at >= ? GROUP BY payment_method",
        (start,),
    ).fetchall()

    top_products = db.execute(
        """
        SELECT si.product_name, SUM(si.quantity) AS qty, SUM(si.line_total) AS revenue
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.created_at >= ?
        GROUP BY si.product_name
        ORDER BY revenue DESC
        LIMIT 5
        """,
        (start,),
    ).fetchall()

    return jsonify(
        {
            "period": period,
            "sales_count": row["count"],
            "subtotal": round(row["subtotal"], 2),
            "ivu": round(row["ivu"], 2),
            "total": round(row["total"], 2),
            "by_payment_method": [dict(r) for r in by_method],
            "top_products": [dict(r) for r in top_products],
        }
    )


@app.route("/api/reports/low-stock", methods=["GET"])
def report_low_stock():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM products WHERE stock <= low_stock_threshold ORDER BY stock ASC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# Se ejecuta al importar el módulo (funciona tanto con `python app.py`
# como al servirse vía gunicorn/WSGI, que no pasa por __main__).
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=True)
