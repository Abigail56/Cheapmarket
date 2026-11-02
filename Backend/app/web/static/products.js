// Admin "Products & prices": add and edit products, and put them on sale without any technical help.
"use strict";

const products = { items: [], categories: [], search: "", category: "", loaded: false };

// The same sum the server uses: prices stay in whole naira
const salePrice = (normal, percent) => Math.floor(normal * (100 - percent) / 100 + 0.5);
const normalPrice = (p) => (p.compare_at_price && p.compare_at_price > p.price ? p.compare_at_price : p.price);
const categoryName = (id) => products.categories.find((c) => c.id === id)?.name || "";

// ---------------------------------------------------------------- switching views
const VIEW_HEADS = {
  deliveries: ["Orders & deliveries", "What needs doing right now."],
  products: ["Products & prices", "Add products, set prices and stock, and run discounts."],
  categories: ["Categories", "The groups customers browse in the shop."],
  zones: ["Delivery areas", "Where you deliver and what it costs."],
  coupons: ["Coupons", "Codes customers can use at checkout."],
  riders: ["Riders", "Add riders, and suspend anyone who has stopped working."],
};

function showView(view) {
  [$("#page-title").textContent, $("#page-sub").textContent] = VIEW_HEADS[view];
  for (const name of ["deliveries", "products", "categories", "zones", "coupons", "riders"]) {
    $(`#view-${name}`).classList.toggle("hidden", name !== view);
  }
  document.querySelectorAll("[data-view]").forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle("secondary", !on);
    b.setAttribute("aria-pressed", on);
  });
  const onError = (e) => toast(e.message, "error");
  if (view === "products" && !products.loaded) loadProducts().catch(onError);
  if (view === "categories") loadCategories().catch(onError);
  if (view === "zones") loadZones().catch(onError);
  if (view === "coupons") loadCoupons().catch(onError);
  if (view === "riders") loadRiders().catch(onError);
  if (view === "deliveries") showTodayLine();
  if (view === "deliveries") map?.invalidateSize();  // the map can't measure itself while hidden
}
document.querySelectorAll("[data-view]").forEach((b) => { b.onclick = () => showView(b.dataset.view); });
fetch(`${API}/auth/config`).then((r) => r.json()).then((c) => { if (c.shop_url) $("#view-shop").href = c.shop_url; }).catch(() => {});

// ---------------------------------------------------------------- loading
async function loadProducts() {
  const [categories, items] = await Promise.all([session.api("/admin/categories"), allProducts()]);
  products.categories = categories;
  products.items = items;
  products.loaded = true;
  const options = categories.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
  $("#sale-scope").innerHTML = `<option value="">Every product in the shop</option>${options}`;
  const current = products.category;
  $("#product-category").innerHTML = `<option value="">All categories</option>${options}`;
  $("#product-category").value = current;
  renderProducts();
}

async function allProducts() {
  const all = [];
  for (let page = 1; ; page += 1) {
    const r = await session.api(`/admin/products?size=100&page=${page}`);
    all.push(...r.items);
    if (page >= r.pages) return all;
  }
}

// ---------------------------------------------------------------- the list
function renderProducts() {
  const search = products.search.trim().toLowerCase();
  const shown = products.items.filter((p) =>
    (!products.category || p.category.id === products.category)
    && (!search || p.name.toLowerCase().includes(search)));
  $("#n-products").textContent = products.items.length;
  $("#product-list").innerHTML = shown.length ? shown.map((p) => `
    <div class="product" data-id="${esc(p.id)}">
      ${p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : `<div class="no-image">No photo</div>`}
      <div class="product-info">
        <strong>${esc(p.name)}</strong>
        <div class="muted">${esc(p.category.name)} · ${esc(p.unit)} · ${p.stock_qty} in stock</div>
        <div class="product-price">
          <b>${naira(p.price)}</b>
          ${p.discount_percent ? `<s class="muted">${naira(p.compare_at_price)}</s> <span class="chip arrived">${p.discount_percent}% off</span>` : ""}
          ${p.is_active ? "" : `<span class="chip cancelled">Hidden from shop</span>`}
        </div>
      </div>
      <div class="row tight product-actions">
        <button type="button" class="small" data-discount>${p.discount_percent ? "Change discount" : "Add discount"}</button>
        <button type="button" class="small secondary" data-edit>Edit</button>
      </div>
    </div>`).join("") : `<p class="muted">No products match.</p>`;
}

$("#product-search").oninput = (e) => { products.search = e.target.value; renderProducts(); };
$("#product-category").onchange = (e) => { products.category = e.target.value; renderProducts(); };
$("#product-add").onclick = () => productForm();
$("#product-list").onclick = (e) => {
  const id = e.target.closest("[data-id]")?.dataset.id;
  const product = products.items.find((p) => p.id === id);
  if (!product) return;
  if (e.target.closest("[data-edit]")) productForm(product);
  if (e.target.closest("[data-discount]")) oneDiscount(product).catch((err) => toast(err.message, "error"));
};

// A whole number from 1 to 90, or null with a message shown
function readPercent(text) {
  const n = Number(String(text).replace("%", "").trim());
  if (!Number.isInteger(n) || n < 1 || n > 90) {
    toast("Enter a whole number from 1 to 90, like 10 for 10% off.", "error");
    return null;
  }
  return n;
}

async function sendDiscount(body) {
  const r = await session.api("/admin/products/discount", { method: "POST", json: body });
  await loadProducts();
  return r.updated;
}

// ---------------------------------------------------------------- discount on one product
async function oneDiscount(p) {
  const normal = normalPrice(p);
  const answer = await ask({
    title: `Discount on ${p.name}`,
    text: `The normal price is ${naira(normal)}. Type the percentage to take off, like 10. Type 0 to end the discount.`,
    input: true, value: p.discount_percent ? String(p.discount_percent) : "", ok: "Save",
  });
  if (answer === null || answer === "") return;
  const percent = answer.trim() === "0" ? 0 : readPercent(answer);
  if (percent === null) return;
  await sendDiscount({ percent, product_ids: [p.id] });
  toast(percent ? `${p.name} now costs ${naira(salePrice(normal, percent))}` : `${p.name} is back to ${naira(normal)}`);
}

// ---------------------------------------------------------------- discount on many products
function scopeWords() {
  const id = $("#sale-scope").value;
  const count = id ? products.items.filter((p) => p.category.id === id).length : products.items.length;
  const label = id ? `all ${count} products in ${categoryName(id)}` : `all ${count} products in the shop`;
  return { id, count, label };
}

$("#sale-form").onsubmit = async (e) => {
  e.preventDefault();
  const percent = readPercent($("#sale-percent").value);
  if (percent === null) return;
  const { id, count, label } = scopeWords();
  if (!count) { toast("There are no products there yet.", "error"); return; }
  const yes = await ask({
    title: `Take ${percent}% off ${label}?`,
    text: "Customers will see the new prices straight away. Any discount these products already have will be replaced.",
    ok: `Take ${percent}% off`,
  });
  if (!yes) return;
  try {
    const updated = await sendDiscount({ percent, category_id: id || null });
    $("#sale-percent").value = "";
    toast(`${percent}% off is now on ${updated} products`);
  } catch (err) { toast(err.message, "error"); }
};

$("#sale-end").onclick = async () => {
  const { id, count, label } = scopeWords();
  if (!count) { toast("There are no products there yet.", "error"); return; }
  const yes = await ask({
    title: `End the discount on ${label}?`,
    text: "These products will go back to their normal prices straight away.",
    ok: "End discount",
  });
  if (!yes) return;
  try {
    await sendDiscount({ percent: 0, category_id: id || null });
    toast("Normal prices are back");
  } catch (err) { toast(err.message, "error"); }
};

// ---------------------------------------------------------------- add / edit form
function productForm(p = null) {
  const normal = p ? normalPrice(p) : "";
  const startPercent = p?.discount_percent || 0;
  const box = document.createElement("dialog");
  box.className = "ask product-dialog";
  box.innerHTML = `<form method="dialog" novalidate>
    <h2>${p ? `Edit ${esc(p.name)}` : "Add a product"}</h2>
    <label for="f-name">Product name</label>
    <input id="f-name" maxlength="200" required value="${esc(p?.name || "")}" placeholder="Rice (local)">
    <label for="f-category">Category</label>
    <select id="f-category" required>${products.categories.map((c) =>
      `<option value="${esc(c.id)}" ${p?.category.id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
    <label for="f-unit">Sold as</label>
    <input id="f-unit" maxlength="50" required value="${esc(p?.unit || "")}" placeholder="5 kg, crate of 30, 1 bunch">
    <div class="form-pair">
      <div><label for="f-price">Normal price (₦)</label><input id="f-price" type="number" min="1" step="1" inputmode="numeric" required value="${esc(normal)}"></div>
      <div><label for="f-percent">Discount (%)</label><input id="f-percent" type="number" min="0" max="90" step="1" inputmode="numeric" value="${startPercent || ""}" placeholder="None"></div>
    </div>
    <p class="banner good" id="f-preview"></p>
    <label for="f-stock">How many are in stock?</label>
    <input id="f-stock" type="number" min="0" step="1" inputmode="numeric" required value="${p ? p.stock_qty : ""}">
    <label for="f-photo">Photo${p?.image_url ? " (choose a file only to replace it)" : ""}</label>
    <input id="f-photo" type="file" accept="image/jpeg,image/png,image/webp">
    <label for="f-description">Description (optional)</label>
    <textarea id="f-description" rows="2">${esc(p?.description || "")}</textarea>
    <label class="check"><input id="f-active" type="checkbox" ${!p || p.is_active ? "checked" : ""}> Show this product in the shop</label>
    <label class="check"><input id="f-featured" type="checkbox" ${p?.is_featured ? "checked" : ""}> Feature it on the home page</label>
    <div class="row mt"><button type="button" class="secondary" data-no>Cancel</button><button type="submit">${p ? "Save changes" : "Add product"}</button></div>
  </form>`;
  document.body.appendChild(box);
  const field = (id) => $(`#f-${id}`, box);
  const preview = () => {
    const price = Number(field("price").value);
    const percent = Number(field("percent").value) || 0;
    field("preview").classList.toggle("hidden", !(price > 0));
    if (!(price > 0)) return;
    // An untouched older discount may not be a round percentage, so show the real price
    const unchanged = p && price === Number(normal) && percent === startPercent;
    field("preview").textContent = `Customers will pay ${naira(unchanged ? p.price : salePrice(price, percent))}`;
  };
  field("price").oninput = preview;
  field("percent").oninput = preview;
  preview();
  $("[data-no]", box).onclick = () => box.close();
  box.addEventListener("close", () => box.remove());
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    const button = $("button[type=submit]", box);
    button.disabled = true;
    try {
      if (await saveProduct(p, field, normal, startPercent)) box.close();
    } catch (err) { toast(err.message, "error"); }
    button.disabled = false;
  };
  box.showModal();
}

function formProblem(field) {
  const price = Number(field("price").value);
  const percent = Number(field("percent").value || 0);
  const stock = field("stock").value;
  if (field("name").value.trim().length < 2) return "Enter the product name.";
  if (!field("category").value) return "Choose a category.";
  if (!field("unit").value.trim()) return "Enter how it's sold, like 5 kg or 1 bunch.";
  if (!(price >= 1)) return "Enter the normal price.";
  if (!Number.isInteger(percent) || percent < 0 || percent > 90) return "The discount must be a whole number from 0 to 90.";
  if (stock === "" || !Number.isInteger(Number(stock)) || Number(stock) < 0) return "Enter how many are in stock.";
  return null;
}

async function saveProduct(p, field, normal, startPercent) {
  const problem = formProblem(field);
  if (problem) { toast(problem, "error"); return false; }
  const price = Number(field("price").value);
  const percent = Number(field("percent").value || 0);
  const stock = Number(field("stock").value);
  const body = {
    name: field("name").value.trim(),
    category_id: field("category").value,
    unit: field("unit").value.trim(),
    description: field("description").value.trim() || null,
    is_active: field("active").checked,
    is_featured: field("featured").checked,
  };
  // Leave the stored price alone unless it was changed here, so saving a name never moves a price
  if (!p || price !== Number(normal) || percent !== startPercent) {
    body.price = percent ? salePrice(price, percent) : price;
    body.compare_at_price = percent ? price : null;
  }
  const file = field("photo").files[0];
  if (file) {
    const form = new FormData();
    form.append("file", file);
    body.image_url = (await session.api("/admin/uploads/images?folder=products", { method: "POST", form })).url;
  }
  if (p) {
    await session.api(`/admin/products/${p.id}`, { method: "PATCH", json: body });
    if (stock !== p.stock_qty) await session.api(`/admin/products/${p.id}/stock`, { method: "POST", json: { set: stock } });
  } else {
    await session.api("/admin/products", { method: "POST", json: { ...body, stock_qty: stock } });
  }
  await loadProducts();
  toast(p ? "Saved" : `${body.name} is added`);
  return true;
}
