const state = {
  products: [],
  cart: {}, // product_id -> quantity
};

// ---------------------------------------------------------------- Tabs
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "inventario") loadInventoryTable();
    if (btn.dataset.tab === "reportes") loadReports();
  });
});

// ------------------------------------------------------------- Helpers
const money = (n) => `$${Number(n).toFixed(2)}`;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Error de red");
  return data;
}

// ------------------------------------------------------------ Productos
async function loadProducts() {
  state.products = await api("/api/products");
  renderProductGrid();
}

function renderProductGrid() {
  const grid = document.getElementById("product-grid");
  grid.innerHTML = "";
  state.products.forEach((p) => {
    const tile = document.createElement("div");
    tile.className = "product-tile" + (p.stock <= 0 ? " out" : "");
    tile.innerHTML = `
      <div class="name">${p.name}</div>
      <div class="price">${money(p.price)}</div>
      <div class="stock">${p.stock > 0 ? `${p.stock} disp.` : "Agotado"}</div>
    `;
    if (p.stock > 0) {
      tile.addEventListener("click", () => addToCart(p.id));
    }
    grid.appendChild(tile);
  });
}

// ----------------------------------------------------------------- Carrito
function addToCart(productId) {
  const product = state.products.find((p) => p.id === productId);
  const inCart = state.cart[productId] || 0;
  if (inCart + 1 > product.stock) return;
  state.cart[productId] = inCart + 1;
  renderCart();
}

function changeQty(productId, delta) {
  const product = state.products.find((p) => p.id === productId);
  const current = state.cart[productId] || 0;
  const next = current + delta;
  if (next <= 0) {
    delete state.cart[productId];
  } else if (next <= product.stock) {
    state.cart[productId] = next;
  }
  renderCart();
}

function renderCart() {
  const container = document.getElementById("cart-items");
  container.innerHTML = "";
  let subtotal = 0;

  Object.entries(state.cart).forEach(([pid, qty]) => {
    const product = state.products.find((p) => p.id === Number(pid));
    if (!product) return;
    const lineTotal = product.price * qty;
    subtotal += lineTotal;

    const line = document.createElement("div");
    line.className = "cart-line";
    line.innerHTML = `
      <span>${product.name}</span>
      <span class="qty-controls">
        <button data-action="minus">−</button>
        <strong style="margin:0 8px">${qty}</strong>
        <button data-action="plus">+</button>
      </span>
      <span>${money(lineTotal)}</span>
    `;
    line.querySelector('[data-action="minus"]').addEventListener("click", () => changeQty(product.id, -1));
    line.querySelector('[data-action="plus"]').addEventListener("click", () => changeQty(product.id, 1));
    container.appendChild(line);
  });

  const ivu = subtotal * 0.115;
  const total = subtotal + ivu;

  document.getElementById("cart-subtotal").textContent = money(subtotal);
  document.getElementById("cart-ivu").textContent = money(ivu);
  document.getElementById("cart-total").textContent = money(total);
  document.getElementById("checkout-btn").disabled = Object.keys(state.cart).length === 0;
}

document.getElementById("checkout-btn").addEventListener("click", async () => {
  const items = Object.entries(state.cart).map(([pid, qty]) => ({
    product_id: Number(pid),
    quantity: qty,
  }));
  const paymentMethod = document.querySelector('input[name="payment"]:checked').value;
  const resultBox = document.getElementById("checkout-result");
  resultBox.innerHTML = "";

  try {
    const sale = await api("/api/sales", {
      method: "POST",
      body: JSON.stringify({ items, payment_method: paymentMethod }),
    });

    let receiptHtml = `
      <div class="receipt">
        <div>Venta #${sale.id} — ${money(sale.total)} total (IVU ${money(sale.ivu)})</div>
    `;
    if (sale.payment_method === "ath_movil") {
      receiptHtml += `<div>Cobro simulado vía ATH Móvil. Referencia:<code>${sale.ath_reference}</code></div>`;
    } else {
      receiptHtml += `<div>Método: ${sale.payment_method}</div>`;
    }
    receiptHtml += `</div>`;
    resultBox.innerHTML = receiptHtml;

    state.cart = {};
    await loadProducts();
    renderCart();
  } catch (err) {
    resultBox.innerHTML = `<div style="color:#d93025">${err.message}</div>`;
  }
});

// --------------------------------------------------------------- Inventario
async function loadInventoryTable() {
  const products = await api("/api/products");
  state.products = products;
  const tbody = document.querySelector("#inventory-table tbody");
  tbody.innerHTML = "";
  products.forEach((p) => {
    const tr = document.createElement("tr");
    if (p.stock <= p.low_stock_threshold) tr.classList.add("low");
    tr.innerHTML = `
      <td>${p.name}</td>
      <td>${p.category}</td>
      <td>${money(p.price)}</td>
      <td>${p.stock}</td>
      <td>
        <button class="link-btn" data-action="edit">Editar</button>
        <button class="link-btn danger" data-action="delete">Eliminar</button>
      </td>
    `;
    tr.querySelector('[data-action="edit"]').addEventListener("click", () => fillProductForm(p));
    tr.querySelector('[data-action="delete"]').addEventListener("click", () => deleteProduct(p.id));
    tbody.appendChild(tr);
  });
}

function fillProductForm(p) {
  document.getElementById("product-id").value = p.id;
  document.getElementById("p-name").value = p.name;
  document.getElementById("p-category").value = p.category;
  document.getElementById("p-price").value = p.price;
  document.getElementById("p-stock").value = p.stock;
  document.getElementById("p-threshold").value = p.low_stock_threshold;
  document.getElementById("product-cancel").style.display = "inline-block";
}

document.getElementById("product-cancel").addEventListener("click", () => {
  document.getElementById("product-form").reset();
  document.getElementById("product-id").value = "";
  document.getElementById("product-cancel").style.display = "none";
});

async function deleteProduct(id) {
  if (!confirm("¿Eliminar este producto?")) return;
  await api(`/api/products/${id}`, { method: "DELETE" });
  await loadInventoryTable();
  await loadProducts();
}

document.getElementById("product-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = document.getElementById("product-id").value;
  const payload = {
    name: document.getElementById("p-name").value.trim(),
    category: document.getElementById("p-category").value.trim() || "General",
    price: document.getElementById("p-price").value,
    stock: document.getElementById("p-stock").value,
    low_stock_threshold: document.getElementById("p-threshold").value,
  };

  try {
    if (id) {
      await api(`/api/products/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/api/products", { method: "POST", body: JSON.stringify(payload) });
    }
    document.getElementById("product-form").reset();
    document.getElementById("product-id").value = "";
    document.getElementById("product-cancel").style.display = "none";
    await loadInventoryTable();
    await loadProducts();
  } catch (err) {
    alert(err.message);
  }
});

// ----------------------------------------------------------------- Reportes
async function loadReports() {
  const period = document.getElementById("report-period").value;
  const summary = await api(`/api/reports/summary?period=${period}`);

  document.getElementById("stat-count").textContent = summary.sales_count;
  document.getElementById("stat-subtotal").textContent = money(summary.subtotal);
  document.getElementById("stat-ivu").textContent = money(summary.ivu);
  document.getElementById("stat-total").textContent = money(summary.total);

  const methodList = document.getElementById("report-by-method");
  methodList.innerHTML = "";
  if (summary.by_payment_method.length === 0) {
    methodList.innerHTML = "<li>Sin ventas en este período</li>";
  }
  summary.by_payment_method.forEach((m) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${m.payment_method} (${m.count})</span><span>${money(m.total)}</span>`;
    methodList.appendChild(li);
  });

  const topList = document.getElementById("report-top-products");
  topList.innerHTML = "";
  if (summary.top_products.length === 0) {
    topList.innerHTML = "<li>Sin datos aún</li>";
  }
  summary.top_products.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${p.product_name} (${p.qty})</span><span>${money(p.revenue)}</span>`;
    topList.appendChild(li);
  });

  const lowStock = await api("/api/reports/low-stock");
  const lowList = document.getElementById("low-stock-list");
  lowList.innerHTML = "";
  if (lowStock.length === 0) {
    lowList.innerHTML = "<li>Todo el inventario está en buen nivel</li>";
  }
  lowStock.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${p.name}</span><span>${p.stock} unid.</span>`;
    lowList.appendChild(li);
  });
}

document.getElementById("report-period").addEventListener("change", loadReports);

// ------------------------------------------------------------------- Init
loadProducts();
